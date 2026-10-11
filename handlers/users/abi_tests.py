"""Abituriyent: sinf → fan → nomli test → «Tayyormisiz?» → quiz → keyingi test taklifi."""
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_RESULTS, BTN_SOLVE
from database.db import Session
from database.models import Attempt, BankTest, Grade, Subject
from database.requests import (effective_plan, grade_subjects, grades, record_result, refund_quota, subject_tests,
                               test_questions, use_quota, user_attempts)
from filters.filters import Registered
from keyboards.inline.buttons import abi_subjects_kb, grades_kb, plans_kb
from services import quiz

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

PAGE = 10  # bir sahifadagi testlar soni


async def _show_grades(message: Message, edit: bool = False):
    items = await grades()
    if not items:
        await message.answer("Hozircha testlar qo'shilmagan. Tez orada qo'shiladi! 🙂")
        return
    text = "🏫 Sinfni tanlang:"
    if edit:
        await message.edit_text(text, reply_markup=grades_kb(items))
    else:
        await message.answer(text, reply_markup=grades_kb(items))


@router.message(F.text == BTN_SOLVE)
async def solve_start(message: Message):
    await _show_grades(message)


@router.callback_query(F.data == "abi:grades")
async def back_to_grades(call: CallbackQuery):
    await call.answer()
    await _show_grades(call.message, edit=True)


@router.callback_query(F.data.startswith("agr:"))
async def pick_grade(call: CallbackQuery):
    grade_id = int(call.data.split(":")[1])
    items = await grade_subjects(grade_id)
    await call.answer()
    if not any(n for _, n in items):
        await call.message.edit_text("Bu sinfda hozircha testlar yo'q.", reply_markup=grades_kb(await grades()))
        return
    async with Session() as s:
        grade = await s.get(Grade, grade_id)
    await call.message.edit_text(f"🏫 <b>{escape(grade.name)}</b>\n\n📘 Fanni tanlang:",
                                 reply_markup=abi_subjects_kb(items, grade_id))


def _tests_kb(subject_id: int, grade_id: int, tests: list, page: int) -> InlineKeyboardMarkup:
    chunk = tests[page * PAGE:(page + 1) * PAGE]
    rows = [[InlineKeyboardButton(text=f"📝 {t.name} · {n} ta", callback_data=f"atest:{t.id}")] for t, n in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"asb:{subject_id}:{page - 1}"))
    if (page + 1) * PAGE < len(tests):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"asb:{subject_id}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Fanlar", callback_data=f"agr:{grade_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("asb:"))
async def pick_subject(call: CallbackQuery):
    parts = call.data.split(":")
    subject_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    async with Session() as s:
        subj = await s.get(Subject, subject_id)
    tests = await subject_tests(subject_id)
    await call.answer()
    pages = f" · {page + 1}/{-(-len(tests) // PAGE)}-sahifa" if len(tests) > PAGE else ""
    await call.message.edit_text(f"📘 <b>{escape(subj.name)}</b> — {len(tests)} ta test{pages}\n\nTestni tanlang:",
                                 reply_markup=_tests_kb(subject_id, subj.grade_id, tests, page))


def _ready_kb(test_id: int, subject_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, boshladik", callback_data=f"ago:{test_id}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=f"asb:{subject_id}"),
    ]])


@router.callback_query(F.data.startswith("atest:"))
async def pick_test(call: CallbackQuery):
    test_id = int(call.data.split(":")[1])
    async with Session() as s:
        t = await s.get(BankTest, test_id)
    if not t:
        await call.answer("Bu test o'chirilgan.", show_alert=True)
        return
    n = len(await test_questions(test_id))
    await call.answer()
    await call.message.answer(f"📝 <b>{escape(t.name)}</b>\n\n{n} ta savol, har biriga ⏱ {t.time_limit} soniya.\n"
                              "Vaqt tugasa, savol javobsiz qoladi.\n\nTayyormisiz?",
                              reply_markup=_ready_kb(test_id, t.subject_id))


@router.callback_query(F.data.startswith("ago:"))
async def go(call: CallbackQuery, db_user):
    test_id = int(call.data.split(":")[1])
    async with Session() as s:
        t = await s.get(BankTest, test_id)
    rows = await test_questions(test_id) if t else []
    if not rows:
        await call.answer("Bu testda savollar topilmadi.", show_alert=True)
        return
    limit = config.PLANS[effective_plan(db_user)]["tests"]
    if db_user.id not in config.ADMINS and limit is not None:
        ok, _ = await use_quota(db_user.id, "tests", limit)
        if not ok:
            await call.answer()
            await call.message.answer(f"⏳ Bugungi limit tugadi: kuniga {limit} ta test.\n"
                                      "Ertaga davom eting yoki tarifni oshiring 🚀", reply_markup=plans_kb())
            return
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    questions = [{"id": q.id, "question": q.text, "options": q.options, "answer": q.answer,
                  "confident": q.confident, "time": q.time_limit or t.time_limit} for q in rows]
    await quiz.start(call.bot, quiz.QuizSession(
        user_id=db_user.id, title=t.name, questions=questions, on_finish=_on_finish, time_limit=t.time_limit,
        meta={"subject": t.subject_id, "test": t.id}, on_result=save_result))


async def save_result(s: quiz.QuizSession, q: dict, ok: bool):
    await record_result(s.user_id, q.get("id"), ok, review=s.meta.get("review", False))


async def _on_finish(s: quiz.QuizSession, bot):
    done = s.idx  # javob berilgan yoki vaqti tugagan savollar
    if done == 0:  # birorta savol ishlanmay to'xtatilgan test limitdan hisoblanmaydi
        await refund_quota(s.user_id, "tests")
        await bot.send_message(s.user_id, "Test bekor qilindi. Limitingiz qaytarildi.")
        return
    async with Session() as db:
        db.add(Attempt(user_id=s.user_id, subject_id=s.meta["subject"], test_id=s.meta["test"], total=done,
                       score=s.score, question_ids=[q["id"] for q in s.questions[:done]]))
        await db.commit()
    tests = await subject_tests(s.meta["subject"])
    ids = [t.id for t, _ in tests]
    rows = []
    if s.meta["test"] in ids and ids.index(s.meta["test"]) + 1 < len(ids):
        nxt = tests[ids.index(s.meta["test"]) + 1][0]
        rows.append([InlineKeyboardButton(text=f"➡️ Keyingi test: {nxt.name}", callback_data=f"atest:{nxt.id}")])
    rows.append([InlineKeyboardButton(text="🔁 Qayta ishlash", callback_data=f"atest:{s.meta['test']}")])
    rows.append([InlineKeyboardButton(text="📋 Testlar ro'yxati", callback_data=f"asb:{s.meta['subject']}")])
    await bot.send_message(s.user_id, quiz.result_text(s, done), protect_content=True,
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == BTN_RESULTS)
async def results(message: Message, db_user):
    items = await user_attempts(db_user.id)
    if not items:
        await message.answer("Hali test ishlamadingiz. «📝 Test ishlash» dan boshlang!")
        return
    lines = []
    for a, name, grade in items:
        pct = round(a.score * 100 / a.total) if a.total else 0
        lines.append(f"{a.created_at:%d.%m} · {escape(grade)} · {escape(name)} — <b>{a.score}/{a.total}</b> ({pct}%)")
    total_q = sum(a.total for a, _, _ in items)
    avg = round(sum(a.score for a, _, _ in items) * 100 / total_q) if total_q else 0
    await message.answer("📈 <b>So'nggi natijalar</b>\n\n" + "\n".join(lines) + f"\n\nO'rtacha: <b>{avg}%</b>")
