"""Telegram quiz (taymerli viktorina) ko'rinishida test o'tkazish.

Har bir savol `send_poll(type="quiz", open_period=...)` bilan yuboriladi. Javob kelsa yoki vaqt tugasa,
keyingi savolga o'tiladi. Sessiyalar xotirada saqlanadi (bot qayta ishga tushsa, yarim test yo'qoladi).
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from html import escape
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, PollAnswer

log = logging.getLogger(__name__)

LETTERS = "ABCDEF"
POLL_QUESTION_MAX = 300
POLL_OPTION_MAX = 100
DEFAULT_TIME = 30
NEXT_DELAY = 1.2  # javobdan keyin to'g'ri javobni ko'rish uchun qisqa pauza

STOP_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Testni yakunlash",
                                                                     callback_data="quiz:stop")]])


@dataclass
class QuizSession:
    user_id: int
    title: str
    questions: list[dict]          # {question, options, answer, confident, time?}
    on_finish: Callable[["QuizSession", Bot], Awaitable[None]]
    time_limit: int = DEFAULT_TIME
    meta: dict = field(default_factory=dict)
    # har bir javobdan keyin: (sessiya, savol, to'g'rimi) — xatolar daftari uchun
    on_result: Callable[["QuizSession", dict, bool], Awaitable[None]] | None = None
    deadline: float | None = None  # mock: umumiy vaqt tugash payti (time.monotonic())
    correct: list[bool] = field(default_factory=list)
    idx: int = 0                   # hozirgi savol tartibi
    score: int = 0
    shown: int = 0                 # foydalanuvchiga ko'rsatilgan savollar
    poll_id: str | None = None
    timer: asyncio.Task | None = None
    finished: bool = False
    stopped: bool = False


_by_user: dict[int, QuizSession] = {}
_by_poll: dict[str, QuizSession] = {}


def is_active(user_id: int) -> bool:
    return user_id in _by_user


async def start(bot: Bot, s: QuizSession):
    old = _by_user.get(s.user_id)
    if old:
        await finish(bot, old, stopped=True)
    _by_user[s.user_id] = s
    timing = (f"umumiy vaqt ⏳ {_fmt(s.deadline - time.monotonic())}" if s.deadline
              else f"har biriga ⏱ {s.time_limit} soniya")
    await bot.send_message(s.user_id, f"🚀 <b>{escape(s.title)}</b>\n{len(s.questions)} ta savol · {timing}",
                           protect_content=True)
    await _send(bot, s)


def _fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _poll_payload(q: dict, idx: int, total: int, left: float | None = None,
                  pick: str = "To'g'ri javobni tanlang ⬆️") -> tuple[str | None, str, list[str]]:
    """(oldindan yuboriladigan matn yoki None, poll savoli, poll variantlari)."""
    head = f"{idx + 1}/{total} · ⏳ {_fmt(left)}\n" if left is not None else f"{idx + 1}/{total}. "
    question = head + q["question"]
    options = q["options"]
    if len(question) <= POLL_QUESTION_MAX and all(len(o) <= POLL_OPTION_MAX for o in options):
        return None, question, options
    # Telegram chegarasidan uzun: savol matni alohida xabarda, poll'da faqat harflar
    full = f"<b>{escape(head)}</b>{escape(q['question'])}\n\n" + \
           "\n".join(f"<b>{LETTERS[i]})</b> {escape(o)}" for i, o in enumerate(options))
    return full, f"{head}{pick}", [LETTERS[i] for i in range(len(options))]


async def _send(bot: Bot, s: QuizSession):
    q = s.questions[s.idx]
    left = None
    if s.deadline:
        left = s.deadline - time.monotonic()
        if left < 5:  # umumiy vaqt tugadi
            await finish(bot, s)
            return
        limit = int(min(600, left))  # Telegram quiz taymeri ko'pi bilan 10 daqiqa
    else:
        limit = q.get("time") or s.time_limit
    pre, question, options = _poll_payload(q, s.idx, len(s.questions), left)
    explanation = None if q.get("confident", True) else "⚠️ Bu savol javobini tekshirib ko'ring"
    try:
        if pre:
            await bot.send_message(s.user_id, pre, protect_content=True)
        msg = await bot.send_poll(s.user_id, question=question, options=options, type="quiz",
                                  correct_option_id=q["answer"], is_anonymous=False, open_period=limit,
                                  explanation=explanation, protect_content=True, reply_markup=STOP_KB)
    except TelegramAPIError as e:
        log.warning("Savol yuborilmadi (%s): %s", s.user_id, e)
        await finish(bot, s, stopped=True)
        return
    s.shown = s.idx + 1
    s.poll_id = msg.poll.id
    _by_poll[s.poll_id] = s
    s.timer = asyncio.create_task(_timeout(bot, s, s.idx, limit))


async def _timeout(bot: Bot, s: QuizSession, idx: int, limit: int):
    await asyncio.sleep(limit + 1)
    if s.finished or s.idx != idx:
        return
    _by_poll.pop(s.poll_id, None)
    await _record(s, False)
    s.idx += 1
    await _next(bot, s)


async def _record(s: QuizSession, ok: bool):
    s.correct.append(ok)
    if s.on_result:
        try:
            await s.on_result(s, s.questions[s.idx], ok)
        except Exception:  # noqa: BLE001
            log.exception("Javobni saqlashda xato")


async def on_answer(bot: Bot, answer: PollAnswer):
    s = _by_poll.pop(answer.poll_id, None)
    if not s or s.finished or not answer.option_ids:
        return
    if s.timer:
        s.timer.cancel()
    ok = answer.option_ids[0] == s.questions[s.idx]["answer"]
    s.score += ok
    await _record(s, ok)
    s.idx += 1
    await asyncio.sleep(NEXT_DELAY)
    await _next(bot, s)


async def _next(bot: Bot, s: QuizSession):
    if s.finished:
        return
    if s.idx < len(s.questions):
        await _send(bot, s)
    else:
        await finish(bot, s)


async def stop(bot: Bot, user_id: int) -> bool:
    s = _by_user.get(user_id)
    if not s:
        return False
    await finish(bot, s, stopped=True)
    return True


async def finish(bot: Bot, s: QuizSession, stopped: bool = False):
    if s.finished:
        return
    s.finished, s.stopped = True, stopped
    if s.timer and s.timer is not asyncio.current_task():
        s.timer.cancel()
    _by_poll.pop(s.poll_id, None)
    if _by_user.get(s.user_id) is s:
        del _by_user[s.user_id]
    try:
        await s.on_finish(s, bot)
    except Exception:  # noqa: BLE001 — natija xabari xatosi testni buzmasligi kerak
        log.exception("Test yakunini yuborishda xato")


def result_text(s: QuizSession, answered_total: int) -> str:
    pct = round(s.score * 100 / answered_total) if answered_total else 0
    medal = "🏆" if pct >= 86 else "🥈" if pct >= 70 else "📚"
    return f"{medal} <b>Test yakunlandi!</b>\n\nNatija: <b>{s.score}/{answered_total}</b> ({pct}%)"
