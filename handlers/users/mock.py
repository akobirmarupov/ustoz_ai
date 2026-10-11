"""Mock imtihon: bir nechta fan bloki, umumiy taymer, bloklar bo'yicha ball."""
import time
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_MOCK
from database.db import Session
from database.models import Grade, Mock, MockAttempt, Subject
from database.requests import effective_plan, grade_mocks, mocks_taken, random_questions
from filters.filters import Registered
from handlers.users.abi_tests import save_result
from keyboards.inline.buttons import plans_kb
from services import quiz

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())


def fmt_ball(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


async def mock_info(mock: Mock) -> tuple[str, int, float]:
    """(bloklar matni, jami savollar, maksimal ball)."""
    async with Session() as s:
        names = {sid: (await s.get(Subject, sid)) for sid in {b["subject_id"] for b in mock.blocks}}
    lines, total, mx = [], 0, 0.0
    for b in mock.blocks:
        subj = names.get(b["subject_id"])
        lines.append(f"• {escape(subj.name if subj else '—')}: {b['count']} ta × {fmt_ball(b['points'])} ball")
        total += b["count"]
        mx += b["count"] * b["points"]
    return "\n".join(lines), total, mx


@router.message(F.text == BTN_MOCK)
async def mocks_list(message: Message):
    mocks = await grade_mocks()
    if not mocks:
        await message.answer("🧪 Hozircha mock imtihonlar qo'shilmagan. Tez orada! 🙂")
        return
    async with Session() as s:
        grades = {g: (await s.get(Grade, g)).name for g in {m.grade_id for m in mocks}}
    rows = [[InlineKeyboardButton(text=f"🧪 {grades[m.grade_id]} · {m.name}", callback_data=f"mock:{m.id}")]
            for m in mocks]
    await message.answer("🧪 <b>Mock imtihon</b> — haqiqiy imtihon kabi, umumiy vaqt va ball bilan.\n\nTanlang:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def _limit_text(plan: str) -> str:
    lim = config.PLANS[plan]["mock"]
    if lim is None:
        return "cheksiz"
    n, days = lim
    return f"{'oyiga' if days >= 28 else 'haftasiga'} {n} ta"


@router.callback_query(F.data.regexp(r"^mock:\d+$"))
async def mock_open(call: CallbackQuery, db_user):
    async with Session() as s:
        mock = await s.get(Mock, int(call.data.split(":")[1]))
    if not mock:
        await call.answer("Bu mock o'chirilgan.", show_alert=True)
        return
    blocks, total, mx = await mock_info(mock)
    await call.answer()
    await call.message.answer(
        f"🧪 <b>{escape(mock.name)}</b>\n\n{blocks}\n\n"
        f"Jami: <b>{total}</b> ta savol · ⏳ <b>{mock.minutes}</b> daqiqa · maksimal <b>{fmt_ball(mx)}</b> ball\n"
        f"Sizning tarifingizda: {_limit_text(effective_plan(db_user))}\n\n"
        "Savollar ketma-ket keladi, orqaga qaytib bo'lmaydi. Vaqt tugasa, imtihon yakunlanadi.\n\nTayyormisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, boshladik", callback_data=f"mockgo:{mock.id}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="mockno")]]))


@router.callback_query(F.data == "mockno")
async def mock_no(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text("Mayli! Tayyor bo'lganingizda «🧪 Mock imtihon» ni bosing 🙂")


@router.callback_query(F.data.startswith("mockgo:"))
async def mock_go(call: CallbackQuery, db_user):
    async with Session() as s:
        mock = await s.get(Mock, int(call.data.split(":")[1]))
    if not mock:
        await call.answer("Bu mock o'chirilgan.", show_alert=True)
        return
    plan = effective_plan(db_user)
    lim = config.PLANS[plan]["mock"]
    if lim and db_user.id not in config.ADMINS and await mocks_taken(db_user.id, lim[1]) >= lim[0]:
        await call.answer()
        await call.message.answer(f"⏳ Mock limiti: {_limit_text(plan)}. Keyinroq urinib ko'ring yoki tarifni oshiring 🚀",
                                  reply_markup=plans_kb())
        return
    questions, blocks = [], []
    for b in mock.blocks:
        rows = await random_questions(b["subject_id"], b["count"])
        for q in rows:
            questions.append({"id": q.id, "question": q.text, "options": q.options, "answer": q.answer,
                              "confident": q.confident, "block": len(blocks)})
        blocks.append({**b, "taken": len(rows)})
    if not questions:
        await call.answer("Bu mock fanlarida hali savollar yo'q.", show_alert=True)
        return
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await quiz.start(call.bot, quiz.QuizSession(
        user_id=db_user.id, title=mock.name, questions=questions, on_finish=_on_finish, on_result=save_result,
        deadline=time.monotonic() + mock.minutes * 60, meta={"mock": mock.id, "blocks": blocks}))


async def _on_finish(s: quiz.QuizSession, bot):
    if s.idx == 0:
        await bot.send_message(s.user_id, "Mock bekor qilindi va limitdan hisoblanmadi.")
        return
    blocks = s.meta["blocks"]
    stats = [{"correct": 0, "count": b["taken"]} for b in blocks]
    for q, ok in zip(s.questions, s.correct):
        stats[q["block"]]["correct"] += ok
    async with Session() as db:
        names = {b["subject_id"]: (await db.get(Subject, b["subject_id"])) for b in blocks}
    details, lines, ball, mx = [], [], 0.0, 0.0
    for b, st in zip(blocks, stats):
        name = names[b["subject_id"]].name if names[b["subject_id"]] else "—"
        got = st["correct"] * b["points"]
        ball += got
        mx += st["count"] * b["points"]
        details.append({"subject": name, "correct": st["correct"], "count": st["count"], "ball": round(got, 1)})
        lines.append(f"{escape(name)}: {st['correct']}/{st['count']} → <b>{fmt_ball(got)}</b> ball")
    async with Session() as db:
        db.add(MockAttempt(user_id=s.user_id, mock_id=s.meta["mock"], ball=round(ball, 1), max_ball=round(mx, 1),
                           details=details))
        await db.commit()
    unanswered = len(s.questions) - s.idx
    note = f"\n⏰ Vaqt tugadi, {unanswered} ta savol ishlanmay qoldi." if unanswered and not s.stopped else ""
    await bot.send_message(
        s.user_id, f"🧪 <b>Mock natijasi</b>\n\n" + "\n".join(lines) +
        f"\n━━━━━━━━━━━━━━\nJami: <b>{fmt_ball(ball)}</b> / {fmt_ball(mx)} ball{note}\n\n"
        "Xato javoblaringiz «❌ Xatolar daftari» ga tushdi. Reytingdagi o'rningiz: «🏆 Reyting» → «🧪 Mock».",
        protect_content=True)
