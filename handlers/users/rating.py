"""Reyting: shu hafta va umumiy — testlarda topilgan to'g'ri javoblar bo'yicha."""
from datetime import date, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_RATING
from database.requests import mock_rating, rating
from filters.filters import Registered

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

TOP = 10
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _since(period: str) -> datetime | None:
    if period == "all":
        return None
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())  # shu haftaning dushanbasi


def _short(name: str) -> str:
    first = (name or "Foydalanuvchi").split()[0]
    return escape(first[:15])


def _kb(period: str) -> InlineKeyboardMarkup:
    tabs = (("week", "📅 Hafta"), ("all", "🏆 Umumiy"), ("mock", "🧪 Mock"))
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("✅ " if period == key else "") + label, callback_data=f"rate:{key}")
        for key, label in tabs]])


async def _mock_text(user_id: int) -> str:
    rows = await mock_rating(exclude=config.ADMINS)
    title = "🧪 <b>Mock reytingi</b>\nHar kimning eng yaxshi natijasi (foiz bo'yicha)"
    if not rows:
        return f"{title}\n\nHali hech kim mock topshirmagan. Birinchi bo'ling! «🧪 Mock imtihon» 🚀"
    from handlers.users.mock import fmt_ball
    lines = []
    for i, (uid, name, ball, mx) in enumerate(rows[:TOP], 1):
        pct = round(ball * 100 / mx) if mx else 0
        me = " ← siz" if uid == user_id else ""
        lines.append(f"{MEDALS.get(i, f'{i}.')} {_short(name)} — <b>{fmt_ball(ball)}</b>/{fmt_ball(mx)} ({pct}%){me}")
    pos = next((i for i, r in enumerate(rows, 1) if r[0] == user_id), None)
    tail = f"\n\n📍 Siz: <b>{pos}</b>-o'rin / {len(rows)}" if pos else "\n\nSiz hali mock topshirmagansiz."
    return f"{title}\n\n" + "\n".join(lines) + tail


async def _text(user_id: int, period: str) -> str:
    if period == "mock":
        return await _mock_text(user_id)
    rows = await rating(_since(period), exclude=config.ADMINS)
    title = "📅 <b>Shu haftalik reyting</b>" if period == "week" else "🏆 <b>Umumiy reyting</b>"
    if not rows:
        return f"{title}\n\nHali hech kim test ishlamagan. Birinchi bo'ling! «📝 Test ishlash» 🚀"
    lines = []
    for i, (uid, name, score, total) in enumerate(rows[:TOP], 1):
        pct = round(score * 100 / total) if total else 0
        me = " ← siz" if uid == user_id else ""
        lines.append(f"{MEDALS.get(i, f'{i}.')} {_short(name)} — <b>{score}</b> ball ({pct}%){me}")
    text = f"{title}\nBall = testlardagi to'g'ri javoblar soni\n\n" + "\n".join(lines)
    pos = next((i for i, r in enumerate(rows, 1) if r[0] == user_id), None)
    if pos is None:
        text += "\n\nSiz hali reytingda yo'qsiz — test ishlang va kiring!"
    elif pos > TOP:
        score = rows[pos - 1][2]
        gap = rows[TOP - 1][2] - score + 1
        text += f"\n\n📍 Siz: <b>{pos}</b>-o'rin / {len(rows)} — {score} ball. Top-{TOP} ga {gap} ball qoldi 💪"
    else:
        text += f"\n\n📍 Siz: <b>{pos}</b>-o'rin / {len(rows)}"
    return text


@router.message(F.text == BTN_RATING)
async def show(message: Message):
    await message.answer(await _text(message.from_user.id, "week"), reply_markup=_kb("week"))


@router.callback_query(F.data.startswith("rate:"))
async def switch(call: CallbackQuery):
    period = call.data.split(":")[1]
    await call.answer()
    text = await _text(call.from_user.id, period)
    if text != call.message.html_text:
        await call.message.edit_text(text, reply_markup=_kb(period))
