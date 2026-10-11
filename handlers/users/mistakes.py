"""Xatolar daftari: xato javob berilgan savollarni qayta ishlash."""
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_MISTAKES
from database.requests import mistake_questions, mistakes_summary
from filters.filters import Registered
from handlers.users.abi_tests import save_result
from services import quiz

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())


async def _summary(user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    items = await mistakes_summary(user_id)
    if not items:
        return ("❌ <b>Xatolar daftari</b>\n\nDaftaringiz bo'sh 🎉\n"
                "Test yoki mockda xato qilgan savollaringiz shu yerga tushadi."), None
    total = sum(n for *_, n in items)
    rows = [[InlineKeyboardButton(text=f"🔁 {grade} · {subj} — {n} ta", callback_data=f"mist:{sid}")]
            for sid, subj, grade, n in items]
    return (f"❌ <b>Xatolar daftari</b> — jami {total} ta savol\n\n"
            "Fanni tanlang va xatolarni qayta ishlang. To'g'ri javob bergan savollaringiz daftardan o'chadi."), \
        InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_MISTAKES)
async def show(message: Message):
    text, kb = await _summary(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("mist:"))
async def review(call: CallbackQuery):
    subject_id = int(call.data.split(":")[1])
    rows = await mistake_questions(call.from_user.id, subject_id, config.MISTAKES_PER_ROUND)
    if not rows:
        await call.answer("Bu fanda xatolar qolmagan 🎉", show_alert=True)
        return
    await call.answer()
    questions = [{"id": q.id, "question": q.text, "options": q.options, "answer": q.answer,
                  "confident": q.confident, "time": q.time_limit} for q in rows]
    await quiz.start(call.bot, quiz.QuizSession(
        user_id=call.from_user.id, title=f"Xatolar ustida ishlash · {len(questions)} ta", questions=questions,
        on_finish=_on_finish, meta={"review": True}, on_result=save_result))


async def _on_finish(s: quiz.QuizSession, bot):
    if s.idx == 0:
        await bot.send_message(s.user_id, "Bekor qilindi.")
        return
    text, kb = await _summary(s.user_id)
    fixed = s.score
    await bot.send_message(s.user_id, f"{quiz.result_text(s, s.idx)}\n\n✅ Daftardan o'chirildi: <b>{fixed}</b> ta\n\n{text}",
                           reply_markup=kb)
