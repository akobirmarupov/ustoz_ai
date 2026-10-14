"""Telegram guruhda test o'tkazish (QuizBot kabi): bitta test, ko'p ishtirokchi, oxirida reyting.

Foydalanuvchi botda testni ochib «👥 Guruhda o'tkazish» ni bosadi → `?startgroup=` havolasi orqali botni guruhga
qo'shadi → guruhda `/start g<part>_<imzo>` keladi → bot «▶️ Start» tugmali e'lon yuboradi.
Start'ni 3 xil odam bosgach, «3, 2, 1» dan keyin savollar ketadi. Test faqat savollar tugaganda
tugaydi. Har bir savol vaqti tugaganda (yoki barcha ishtirokchilar javob berganda) keyingisiga o'tiladi.
«📤 Boshqa guruhga» tugmasi orqali istalgan a'zo testni o'z guruhiga olib keta oladi.
Guruhdagi barcha matnlar uch tilda: o'zbek, rus, ingliz.
Sessiyalar xotirada saqlanadi (bot qayta ishga tushsa, yarim test yo'qoladi).
"""
import asyncio
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, PollAnswer

from data import config
from services.quiz import _poll_payload

log = logging.getLogger(__name__)

NEXT_DELAY = 2       # hamma javob bergach, keyingi savoldan oldin pauza
MIN_GAP = 4          # guruhga daqiqasiga ~20 xabar chegarasi: savollar orasida kamida shuncha soniya
START_VOTES = 3      # test shuncha xil odam «Start» ni bosganda boshlanadi
TOP = 10
MEDALS = ("🥇", "🥈", "🥉")


def tr(uz: str, ru: str, en: str) -> str:
    """Guruh xabari uch tilda."""
    return f"🇺🇿 {uz}\n🇷🇺 {ru}\n🇬🇧 {en}"


SHORT = " / "  # tugma ogohlantirishlari (200 belgi) uchun bir qatorda


ALREADY = SHORT.join(("Siz allaqachon bosdingiz", "Вы уже нажали", "You already pressed"))
EXPIRED = SHORT.join(("Bu tugma eskirgan", "Кнопка устарела", "This button is outdated"))
RUNNING = SHORT.join(("Bu guruhda test ketmoqda", "В этой группе уже идёт тест", "A quiz is already running here"))
ONLY_OWNER = SHORT.join(("Faqat test egasi yoki admin", "Только владелец теста или админ", "Only the quiz owner or an admin"))


def payload(part_id: int) -> str:
    """Guruh havolasi uchun imzolangan kod: begona odam boshqa birovning testini raqam bilan ocholmasligi uchun."""
    sig = hmac.new(config.BOT_TOKEN.encode(), f"g{part_id}".encode(), hashlib.sha256).hexdigest()[:10]
    return f"g{part_id}_{sig}"


def parse_payload(arg: str | None) -> int | None:
    if not arg or not arg.startswith("g") or "_" not in arg:
        return None
    num = arg[1:].split("_", 1)[0]
    if not num.isdigit() or not hmac.compare_digest(payload(int(num)), arg):
        return None
    return int(num)


async def group_link(bot: Bot, part_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?startgroup={payload(part_id)}"


@dataclass
class Player:
    name: str
    correct: int = 0
    seconds: float = 0.0  # to'g'ri javoblarga ketgan vaqt (teng ochkoda tezroq yuqorida)


@dataclass
class GroupQuiz:
    chat_id: int
    owner_id: int
    part_id: int
    title: str
    questions: list[dict]
    time_limit: int
    started: bool = False
    ready: dict[int, str] = field(default_factory=dict)  # «Start» ni bosganlar: id → ism
    finished: bool = False
    idx: int = 0
    poll_id: str | None = None
    poll_msg_id: int | None = None
    sent_at: float = 0.0
    timer: asyncio.Task | None = None
    players: dict[int, Player] = field(default_factory=dict)
    answered: set[int] = field(default_factory=set)  # hozirgi savolga javob berganlar
    expected: set[int] = field(default_factory=set)  # savol yuborilganda ma'lum bo'lgan qatnashchilar


_by_chat: dict[int, GroupQuiz] = {}
_by_poll: dict[str, GroupQuiz] = {}


def get(chat_id: int) -> GroupQuiz | None:
    return _by_chat.get(chat_id)


async def share_button(bot: Bot, part_id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="📤 Share", url=await group_link(bot, part_id))


def _head(s: GroupQuiz) -> str:
    return f"🎲 <b>{escape(s.title)}</b>\n🖊 {len(s.questions)} · ⏱ {s.time_limit} s"


async def lobby(bot: Bot, s: GroupQuiz) -> tuple[str, InlineKeyboardMarkup]:
    _by_chat[s.chat_id] = s
    n = START_VOTES
    text = _head(s) + "\n\n" + tr(
        f"Test {n} kishi «Start» ni bosganda boshlanadi. Javob bergan har bir a'zo reytingga kiradi.",
        f"Тест начнётся, когда {n} человека нажмут «Start». Каждый ответивший попадает в рейтинг.",
        f"The quiz starts when {n} people press «Start». Everyone who answers gets on the leaderboard.")
    if s.ready:
        text += (f"\n\n✅ Tayyor / Готовы / Ready ({len(s.ready)}/{n}): "
                 + ", ".join(escape(name) for name in s.ready.values()))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"▶️ Start ({len(s.ready)}/{n})", callback_data="gq:go"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="gq:cancel")],
        [await share_button(bot, s.part_id)]])
    return text, kb


def press_start(s: GroupQuiz, user_id: int, name: str) -> bool | None:
    """«Start» bosildi: None — bu odam avval bosgan, True — yetarli odam yig'ildi (test boshlanadi)."""
    if user_id in s.ready:
        return None
    s.ready[user_id] = name
    if len(s.ready) >= START_VOTES:
        s.started = True  # bir vaqtda bir necha kishi bossa ham ikki marta boshlanmasligi uchun darhol
        return True
    return False


async def keep_on_top(bot: Bot, s: GroupQuiz, msg: Message):
    """Boshlangan test e'loni guruhda qoladi: «📤 Share» tugmasi bilan, tepaga mahkamlanadi."""
    text = _head(s) + "\n\n" + tr(
        "▶️ Test ketmoqda! O'z guruhingizda o'tkazish uchun pastdagi tugmani bosing 👇",
        "▶️ Тест идёт! Чтобы провести его в своей группе, нажмите кнопку ниже 👇",
        "▶️ The quiz is on! To run it in your own group, press the button below 👇")
    kb = InlineKeyboardMarkup(inline_keyboard=[[await share_button(bot, s.part_id)]])
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramAPIError as e:
        log.info("E'lon tahrirlanmadi (%s): %s", s.chat_id, e)
    try:  # botda «xabarlarni mahkamlash» huquqi bo'lmasa — shunchaki o'tkazib yuboriladi
        await bot.pin_chat_message(s.chat_id, msg.message_id, disable_notification=True)
    except TelegramAPIError as e:
        log.info("E'lon mahkamlanmadi (%s): %s", s.chat_id, e)


async def can_control(bot: Bot, s: GroupQuiz, user_id: int) -> bool:
    if user_id == s.owner_id:
        return True
    try:
        member = await bot.get_chat_member(s.chat_id, user_id)
    except TelegramAPIError:
        return False
    return member.status in ("creator", "administrator")


def cancel(s: GroupQuiz):
    s.finished = True
    if _by_chat.get(s.chat_id) is s:
        del _by_chat[s.chat_id]


async def start(bot: Bot, s: GroupQuiz):
    s.started = True
    head = f"🚀 <b>{escape(s.title)}</b>\n" + SHORT.join(("Boshladik!", "Начинаем!", "Let's go!"))
    msg = await _call(bot.send_message, s.chat_id, f"{head}\n\n3️⃣")
    for n in ("2️⃣", "1️⃣"):  # yangi xabar emas, tahrir — guruh xabar chegarasini sarflamaydi
        await asyncio.sleep(1)
        try:
            await bot.edit_message_text(f"{head}\n\n{n}", chat_id=s.chat_id, message_id=msg.message_id)
        except TelegramAPIError:
            pass
    await asyncio.sleep(1)
    try:
        await bot.edit_message_text(f"{head}\n\n🍀 " + SHORT.join(("Omad!", "Удачи!", "Good luck!")), chat_id=s.chat_id, message_id=msg.message_id)
    except TelegramAPIError:
        pass
    await _send(bot, s)


async def _call(method, *args, **kw):
    """Guruh xabar chegarasidan oshsa (429), kutib yana bir marta urinadi."""
    try:
        return await method(*args, **kw)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        return await method(*args, **kw)


async def _send(bot: Bot, s: GroupQuiz):
    q = s.questions[s.idx]
    limit = q.get("time") or s.time_limit
    pre, question, options = _poll_payload(q, s.idx, len(s.questions), pick="⬆️")
    try:
        if pre:
            await _call(bot.send_message, s.chat_id, pre, protect_content=True)
        msg = await _call(bot.send_poll, s.chat_id, question=question, options=options, type="quiz",
                          correct_option_id=q["answer"], is_anonymous=False, open_period=limit,
                          protect_content=True)
    except TelegramAPIError as e:
        log.warning("Guruhga savol yuborilmadi (%s): %s", s.chat_id, e)
        await finish(bot, s, note="⚠️ " + SHORT.join((
            "Savolni yuborib bo'lmadi (botga so'rovnoma yuborish huquqini bering)",
            "Не удалось отправить вопрос (дайте боту право отправлять опросы)",
            "Could not send the question (allow the bot to send polls)")))
        return
    s.answered, s.expected = set(), set(s.players)
    s.poll_id, s.poll_msg_id, s.sent_at = msg.poll.id, msg.message_id, time.monotonic()
    _by_poll[s.poll_id] = s
    s.timer = asyncio.create_task(_advance(bot, s, s.idx, limit + 1))


async def _advance(bot: Bot, s: GroupQuiz, idx: int, delay: float):
    await asyncio.sleep(delay)
    if s.finished or s.idx != idx:
        return
    s.idx += 1  # boshqa taymer/javob shu savolni ikkinchi marta yopmasligi uchun darhol
    _by_poll.pop(s.poll_id, None)
    if s.idx >= len(s.questions):
        await finish(bot, s)
        return
    wait = MIN_GAP - (time.monotonic() - s.sent_at)
    if wait > 0:
        await asyncio.sleep(wait)
    if not s.finished:
        await _send(bot, s)


async def on_answer(bot: Bot, answer: PollAnswer) -> bool:
    """Guruh testining javobi bo'lsa — hisoblaydi va True qaytaradi."""
    s = _by_poll.get(answer.poll_id)
    if not s:
        return False
    user = answer.user
    if s.finished or not user or not answer.option_ids or user.id in s.answered:
        return True
    s.answered.add(user.id)
    p = s.players.setdefault(user.id, Player(name=user.full_name))
    if answer.option_ids[0] == s.questions[s.idx]["answer"]:
        p.correct += 1
        p.seconds += time.monotonic() - s.sent_at
    # Oldingi savollarda qatnashganlarning hammasi javob berdi — vaqt tugashini kutmaymiz
    if s.expected and s.answered >= s.expected:
        if s.timer:
            s.timer.cancel()
        try:
            await bot.stop_poll(s.chat_id, s.poll_msg_id)
        except TelegramAPIError:
            pass
        s.timer = asyncio.create_task(_advance(bot, s, s.idx, NEXT_DELAY))
    return True


def leaderboard(s: GroupQuiz) -> str:
    total = len(s.questions)
    ranked = sorted(s.players.values(), key=lambda p: (-p.correct, p.seconds))
    if not ranked:
        return SHORT.join(("Hech kim qatnashmadi", "Никто не участвовал", "Nobody took part"))
    lines = []
    for i, p in enumerate(ranked[:TOP]):
        place = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        lines.append(f"{place} {escape(p.name)} — <b>{p.correct}/{total}</b> ({p.seconds:.1f} s)")
    more = f"\n… +{len(ranked) - TOP}" if len(ranked) > TOP else ""
    return f"👥 Qatnashchilar / Участники / Players: <b>{len(ranked)}</b>\n\n" + "\n".join(lines) + more


async def finish(bot: Bot, s: GroupQuiz, note: str = ""):
    if s.finished:
        return
    s.finished = True
    if s.timer and s.timer is not asyncio.current_task():
        s.timer.cancel()
    _by_poll.pop(s.poll_id, None)
    if _by_chat.get(s.chat_id) is s:
        del _by_chat[s.chat_id]
    head = f"🏁 <b>{escape(s.title)}</b>\n" + SHORT.join(("Test yakunlandi", "Тест завершён", "Quiz finished"))
    if s.idx < len(s.questions):
        head += f" ({s.idx}/{len(s.questions)})"
    text = head + (f"\n{note}" if note else "") + "\n\n" + leaderboard(s)
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Again", callback_data=f"gq:again:{s.part_id}"),
            await share_button(bot, s.part_id)]])
        await _call(bot.send_message, s.chat_id, text, reply_markup=kb)
    except TelegramAPIError as e:
        log.warning("Guruhga natija yuborilmadi (%s): %s", s.chat_id, e)
