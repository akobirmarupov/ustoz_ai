"""Telegram guruhda test o'tkazish (QuizBot kabi): bitta test, ko'p ishtirokchi, oxirida reyting.

Foydalanuvchi botda testni ochib «👥 Guruhda o'tkazish» ni bosadi → `?startgroup=` havolasi orqali botni guruhga
qo'shadi → guruhda `/start g<part>_<imzo>` keladi → bot «▶️ Boshlash» tugmali e'lon yuboradi.
Har bir savol vaqti tugaganda (yoki barcha ishtirokchilar javob berganda) keyingisiga o'tiladi.
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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, PollAnswer

from data import config
from services.quiz import _poll_payload

log = logging.getLogger(__name__)

NEXT_DELAY = 2       # hamma javob bergach, keyingi savoldan oldin pauza
MIN_GAP = 4          # guruhga daqiqasiga ~20 xabar chegarasi: savollar orasida kamida shuncha soniya
MAX_IDLE = 3         # ketma-ket shuncha savolga hech kim javob bermasa, test to'xtaydi
TOP = 10
MEDALS = ("🥇", "🥈", "🥉")

STOP_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ To'xtatish", callback_data="gq:stop")]])


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
    finished: bool = False
    idx: int = 0
    poll_id: str | None = None
    poll_msg_id: int | None = None
    sent_at: float = 0.0
    timer: asyncio.Task | None = None
    players: dict[int, Player] = field(default_factory=dict)
    answered: set[int] = field(default_factory=set)  # hozirgi savolga javob berganlar
    expected: set[int] = field(default_factory=set)  # savol yuborilganda ma'lum bo'lgan qatnashchilar
    idle: int = 0


_by_chat: dict[int, GroupQuiz] = {}
_by_poll: dict[str, GroupQuiz] = {}


def get(chat_id: int) -> GroupQuiz | None:
    return _by_chat.get(chat_id)


def lobby(s: GroupQuiz) -> tuple[str, InlineKeyboardMarkup]:
    _by_chat[s.chat_id] = s
    text = (f"🎲 <b>{escape(s.title)}</b>\n"
            f"🖊 {len(s.questions)} ta savol · ⏱ har biriga {s.time_limit} soniya\n\n"
            "Javob bergan har bir guruh a'zosi reytingga kiradi. Teng natijada tezroq javob bergan yuqorida.\n\n"
            "🏁 Testni qo'shgan odam yoki guruh admini «▶️ Boshlash» ni bossin.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ Boshlash", callback_data="gq:go"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="gq:cancel")]])
    return text, kb


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
    await _call(bot.send_message, s.chat_id, f"🚀 <b>{escape(s.title)}</b> boshlandi! Omad 🍀")
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
    pre, question, options = _poll_payload(q, s.idx, len(s.questions))
    try:
        if pre:
            await _call(bot.send_message, s.chat_id, pre, protect_content=True)
        msg = await _call(bot.send_poll, s.chat_id, question=question, options=options, type="quiz",
                          correct_option_id=q["answer"], is_anonymous=False, open_period=limit,
                          protect_content=True, reply_markup=STOP_KB)
    except TelegramAPIError as e:
        log.warning("Guruhga savol yuborilmadi (%s): %s", s.chat_id, e)
        await finish(bot, s, note="⚠️ Savolni yuborib bo'lmadi (botda so'rovnoma yuborish huquqi bormi?).")
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
    s.idle = 0 if s.answered else s.idle + 1
    if s.idle >= MAX_IDLE:
        await finish(bot, s, note="😴 Ketma-ket bir necha savolga hech kim javob bermadi — test to'xtatildi.")
        return
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
        return "Hech kim qatnashmadi."
    lines = []
    for i, p in enumerate(ranked[:TOP]):
        place = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        lines.append(f"{place} {escape(p.name)} — <b>{p.correct}/{total}</b> ({p.seconds:.1f} s)")
    more = f"\n… va yana {len(ranked) - TOP} kishi" if len(ranked) > TOP else ""
    return f"👥 Qatnashchilar: <b>{len(ranked)}</b>\n\n" + "\n".join(lines) + more


async def finish(bot: Bot, s: GroupQuiz, note: str = ""):
    if s.finished:
        return
    s.finished = True
    if s.timer and s.timer is not asyncio.current_task():
        s.timer.cancel()
    _by_poll.pop(s.poll_id, None)
    if _by_chat.get(s.chat_id) is s:
        del _by_chat[s.chat_id]
    head = f"🏁 <b>{escape(s.title)}</b> yakunlandi!"
    if s.idx < len(s.questions):
        head += f" ({s.idx}/{len(s.questions)} savol)"
    text = head + (f"\n{note}" if note else "") + "\n\n" + leaderboard(s)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔁 Qayta o'tkazish", callback_data=f"gq:again:{s.part_id}")]])
    try:
        await _call(bot.send_message, s.chat_id, text, reply_markup=kb)
    except TelegramAPIError as e:
        log.warning("Guruhga natija yuborilmadi (%s): %s", s.chat_id, e)
