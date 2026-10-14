"""Test tayyorlash (javobsiz testlar yoki kitobcha) va testni bot ichida ishlash."""
import re
import time
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_TEST
from database.db import Session
from database.models import Order, TestPart, TestSet, User
from database.requests import enqueue, set_parts, user_test_sets
from services.worker import _finish_if_complete
from filters.filters import Registered
from keyboards.default.menu import cancel_menu, student_menu
from keyboards.inline.buttons import (after_test_kb, part_menu_kb, part_size_kb, parts_kb, set_menu_kb, test_source_kb,
                                     time_kb)
from services import group_quiz, quiz
from services.parser import FORMAT_HELP, parse_tests
from services.extract import SUPPORTED
from services.payments import money, start_payment
from states.states import StudentManual, TestOrder

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

# ---------------- Buyurtma ----------------

@router.message(F.text == BTN_TEST)
async def test_start(message: Message, state: FSMContext, db_user):
    await state.clear()
    gift = "\n\n🎁 Birinchi testingiz to'liq bepul!" if not db_user.free_test_used else ""
    if db_user.id in config.ADMINS:
        gift = "\n\n👑 Admin uchun bepul."
    await message.answer(
        "✅ <b>Test tayyorlash</b>\n\n"
        "🤖 <b>AI: javobsiz testlar</b> — fayldagi testlarga AI javob topadi.\n"
        "🤖 <b>AI: kitobcha</b> — kitob matnidan AI siz tanlagan sondagi testlarni tuzadi.\n"
        "📄 <b>Avtomatik</b> — javoblari belgilangan tayyor testni quiz ko'rinishiga keltiradi.\n"
        "✍️ <b>Qo'lda</b> — savollarni o'zingiz yozasiz.\n\n"
        "📝 Testga nom berasiz va har bir testdagi savollar sonini tanlaysiz (20/30/40/50). Fayl shu sondan "
        "bo'linadi: masalan «Matematika» → Matematika 1, Matematika 2 ...\n"
        "👥 Tayyor testlarni o'zingiz ishlashingiz yoki Telegram guruhda o'tkazishingiz mumkin.\n\n"
        f"💰 AI orqali: <b>{money(config.PRICES['test'])}</b>\n"
        f"💰 Avtomatik va Qo'lda: <b>{money(config.PRICES['test_auto'])}</b>\n"
        "To'lov test tayyorlashdan oldin qilinadi." + gift,
        reply_markup=test_source_kb())


@router.callback_query(F.data.startswith("tsrc:"))
async def test_source(call: CallbackQuery, state: FSMContext):
    source = call.data.split(":")[1]
    await state.update_data(source=source)
    await call.answer()
    await state.set_state(TestOrder.name)
    await call.message.edit_text("✍️ Test nomini yozing.\nMasalan: <b>Matematika ko'paytirish</b>")


async def _ask_time(call: CallbackQuery, state: FSMContext):
    await state.set_state(TestOrder.time)
    await call.message.edit_text("⏱ Har bir savolga qancha vaqt berilsin?", reply_markup=time_kb("ttime"))


PRICE_KEY = {"auto": "test_auto", "manual": "test_manual"}  # qolganlari (AI) — "test"
ORDER_FIELDS = ("source", "time", "parts", "per_part", "name", "size")


@router.callback_query(TestOrder.time, F.data.startswith("ttime:"))
async def test_time(call: CallbackQuery, state: FSMContext):
    await state.update_data(time=int(call.data.split(":")[1]))
    await call.answer()
    data = await state.get_data()
    await state.clear()
    async with Session() as s:
        user = await s.get(User, call.from_user.id)
        is_admin = user.id in config.ADMINS
        free = not user.free_test_used and not is_admin
        if free:
            user.free_test_used = True
        opened = is_admin or free
        order = Order(user_id=user.id, kind="test", is_free=opened,
                      price=0 if is_admin else config.PRICES[PRICE_KEY.get(data["source"], "test")],
                      title=(data.get("name") or "Test")[:250], status="paid" if opened else "awaiting_payment",
                      params={k: data.get(k) for k in ORDER_FIELDS} | {"admin": is_admin, "free": free})
        s.add(order)
        await s.commit()
    if opened:
        await call.message.edit_text("🎁 Birinchi testingiz bepul!" if free else "👑 Admin uchun bepul.")
        await _begin(call.message, state, order)
        return
    what = "savollarni yozishni boshlaysiz" if data["source"] == "manual" else "faylni yuborasiz"
    await call.message.edit_text(f"💳 Test tayyorlash pullik. To'lov tasdiqlangach {what}.")
    await start_payment(call.bot, order.user_id, "order", order.price, KIND_LABEL.get(data["source"], "Test"),
                        order_id=order.id)


KIND_LABEL = {"tests": "Test: AI javob topadi", "book": "Test: AI kitobchadan tuzadi",
              "auto": "Test: avtomatik", "manual": "Test: qo'lda"}


def start_kb(order: Order) -> InlineKeyboardMarkup:
    text = "✍️ Savollarni yozishni boshlash" if order.params.get("source") == "manual" else "📎 Faylni yuborish"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"tstart:{order.id}")]])


async def _begin(message: Message, state: FSMContext, order: Order):
    """To'langan (yoki bepul) buyurtma bo'yicha fayl kutish yoki savol yozishni boshlaydi."""
    p = order.params
    await state.clear()
    await state.update_data(order_id=order.id, **{k: p.get(k) for k in ORDER_FIELDS})
    if p["source"] == "manual":
        await state.update_data(questions=[])
        await state.set_state(StudentManual.question)
        await message.answer(
            f"✍️ <b>{escape(p['name'])}</b> — {p['size']} ta savol, har biriga {p['time']} soniya.\n\n"
            "1-savol matnini yuboring.\n\n"
            "💡 Tezroq usul: bir xabarda bir nechta savolni javobi bilan yuborsangiz ham bo'ladi:\n"
            "<code>1. 2 + 2 = ?\nA) 3\n*B) 4\nC) 5</code>", reply_markup=cancel_menu())
        return
    await state.set_state(TestOrder.file)
    hint = "\n\n" + FORMAT_HELP if p["source"] == "auto" else ""
    await message.answer(f"⏱ Har bir savolga {p['time']} soniya.\n\n"
                         "📎 Faylni yuboring (PDF, Word .docx yoki .txt, 20 MB gacha)." + hint,
                         reply_markup=cancel_menu())


@router.callback_query(F.data.startswith("tstart:"))
async def resume(call: CallbackQuery, state: FSMContext):
    async with Session() as s:
        order = await s.get(Order, int(call.data.split(":")[1]))
    if not order or order.user_id != call.from_user.id:
        await call.answer("Topilmadi", show_alert=True)
        return
    if order.status != "paid":
        await call.answer("Bu buyurtma allaqachon ishlatilgan yoki hali to'lanmagan.", show_alert=True)
        return
    await call.answer()
    await _begin(call.message, state, order)


@router.message(TestOrder.name, F.text)
async def test_name(message: Message, state: FSMContext):
    name = message.text.strip()[:100]
    if len(name) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yozing:")
        return
    await state.update_data(name=name)
    await state.set_state(TestOrder.size)
    if (await state.get_data())["source"] == "manual":
        ask = "Testda nechta savol bo'lsin?"
    else:
        ask = (f"Har bir testda nechta savol bo'lsin?\n\n"
               f"Masalan 40 ta tanlasangiz, 500 ta savol 40 tadan bo'linadi, oxirgisida qolgan 20 tasi bo'ladi:\n"
               f"<i>{escape(name)} 1, {escape(name)} 2, ... {escape(name)} 13</i>")
    await message.answer(f"📝 <b>{escape(name)}</b>\n\n{ask}", reply_markup=part_size_kb())


@router.callback_query(TestOrder.size, F.data.startswith("tsize:"))
async def test_size(call: CallbackQuery, state: FSMContext):
    n = int(call.data.split(":")[1])
    await state.update_data(size=n, per_part=n)
    await call.answer()
    if (await state.get_data())["source"] == "book":
        await state.set_state(TestOrder.parts)
        await call.message.edit_text(f"✅ Har birida {n} ta savol.\n\n📚 Kitobchadan nechta test tuzilsin?",
                                     reply_markup=parts_kb())
        return
    await _ask_time(call, state)


@router.callback_query(TestOrder.parts, F.data.startswith("bparts:"))
async def book_parts(call: CallbackQuery, state: FSMContext):
    await state.update_data(parts=int(call.data.split(":")[1]))
    await call.answer()
    await _ask_time(call, state)


@router.message(TestOrder.file, F.document)
async def test_file(message: Message, state: FSMContext):
    doc = message.document
    ext = Path(doc.file_name or "").suffix.lower()
    if ext not in SUPPORTED:
        await message.answer("Faqat PDF, Word (.docx) yoki .txt fayl qabul qilinadi. "
                             "Eski .doc faylni Word'da .docx qilib saqlab yuboring.")
        return
    if (doc.file_size or 0) > config.MAX_FILE_MB * 1024 * 1024:
        await message.answer(f"Fayl {config.MAX_FILE_MB} MB dan katta. Kichikroq fayl yuboring.")
        return
    data = await state.get_data()
    async with Session() as s:
        order = await s.get(Order, data.get("order_id", 0))
    if not order or order.status != "paid":
        await state.clear()
        await message.answer("Avval «✅ Test tayyorlash» dan test turini tanlang.", reply_markup=student_menu())
        return
    await state.clear()

    path = config.UPLOADS_DIR / f"{message.from_user.id}_{int(time.time())}{ext}"
    await message.bot.download(doc, destination=path)

    async with Session() as s:
        o = await s.get(Order, order.id)
        o.status = "preparing"
        ts = TestSet(order_id=order.id, user_id=order.user_id, source=data["source"], file_path=str(path),
                     file_name=doc.file_name[:250], name=(data.get("name") or "")[:128],
                     parts_count=data.get("parts") or 0, per_part=data.get("per_part"),
                     time_limit=data["time"], unlocked=True)
        s.add(ts)
        await s.commit()

    await enqueue("test_prepare", ts.id)
    await message.answer("⏳ Fayl qabul qilindi va o'qilmoqda. Natijani shu yerga yuboraman.",
                         reply_markup=student_menu())


@router.message(TestOrder.file)
async def test_file_wrong(message: Message):
    await message.answer("Iltimos, faylni hujjat (document) sifatida yuboring.")


@router.callback_query(F.data.startswith("unlock:"))
async def unlock(call: CallbackQuery):
    set_id = int(call.data.split(":")[1])
    async with Session() as s:
        ts = await s.get(TestSet, set_id)
    if not ts or ts.user_id != call.from_user.id:
        await call.answer("Topilmadi", show_alert=True)
        return
    if ts.unlocked:
        await call.answer("Bu testlar allaqachon ochilgan ✅", show_alert=True)
        return
    await call.answer()
    async with Session() as s:
        order = await s.get(Order, ts.order_id)
    await start_payment(call.bot, ts.user_id, "order", order.price, f"Test: {ts.title}", order_id=ts.order_id)


# ---------------- Qo'lda yozish ----------------

DONE_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tugatish", callback_data="tman:done")]])


async def _manual_progress(message: Message, state: FSMContext):
    data = await state.get_data()
    n, size = len(data["questions"]), data["size"]
    if n >= size:
        await _manual_finish(message, state, message.chat.id)
        return
    await state.set_state(StudentManual.question)
    await message.answer(f"✅ Saqlandi: <b>{n}/{size}</b>.\n\n{n + 1}-savol matnini yuboring:", reply_markup=DONE_KB)


@router.message(StudentManual.question, F.text)
async def manual_question(message: Message, state: FSMContext):
    data = await state.get_data()
    parsed, _ = parse_tests(message.text)
    if parsed:  # bir xabarda javobi bilan bir nechta savol
        room = data["size"] - len(data["questions"])
        await state.update_data(questions=data["questions"] + parsed[:room])
        await _manual_progress(message, state)
        return
    await state.update_data(q_text=message.text.strip()[:1000])
    await state.set_state(StudentManual.options)
    await message.answer("Variantlarni yuboring — <b>har biri yangi qatorda</b> (2 dan 6 tagacha):\n"
                         "<code>3\n4\n5\n6</code>")


@router.message(StudentManual.options, F.text)
async def manual_options(message: Message, state: FSMContext):
    opts = [re.sub(r"^\s*[A-Fa-fА-Еа-е]\s*[).]\s*", "", ln).strip() for ln in message.text.split("\n")]
    opts = [o[:300] for o in opts if o]
    if not 2 <= len(opts) <= 6:
        await message.answer("2 tadan 6 tagacha variant kerak, har biri yangi qatorda. Qaytadan yuboring:")
        return
    await state.update_data(q_opts=opts)
    await state.set_state(StudentManual.answer)
    rows = [[InlineKeyboardButton(text=f"{'ABCDEF'[i]}) {o[:40]}", callback_data=f"tman:{i}")] for i, o in enumerate(opts)]
    await message.answer("✅ To'g'ri javobni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(StudentManual.answer, F.data.regexp(r"^tman:\d$"))
async def manual_answer(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    q = {"question": data["q_text"], "options": data["q_opts"], "answer": int(call.data.split(":")[1]),
         "confident": True}
    await state.update_data(questions=data["questions"] + [q])
    await call.answer("Saqlandi ✅")
    await call.message.edit_text(f"✅ To'g'ri javob: <b>{'ABCDEF'[q['answer']]}</b>")
    await _manual_progress(call.message, state)


@router.callback_query(F.data == "tman:done")
async def manual_done(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not (await state.get_data()).get("questions"):
        await call.message.answer("Hali birorta savol kiritilmadi.")
        return
    await _manual_finish(call.message, state, call.from_user.id)


async def _manual_finish(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    await state.clear()
    questions = data["questions"]
    async with Session() as s:
        order = await s.get(Order, data["order_id"])
        order.status = "done"
        ts = TestSet(order_id=order.id, user_id=user_id, source="manual", file_path="", file_name=data["name"][:250],
                     name=data["name"][:128], parts_count=1, time_limit=data["time"], unlocked=True)
        s.add(ts)
        await s.flush()
        s.add(TestPart(set_id=ts.id, number=1, questions=questions, status="ready"))
        await s.commit()
    await message.answer(f"🏁 <b>{escape(data['name'])}</b> saqlandi: {len(questions)} ta savol.",
                         reply_markup=student_menu())
    await _finish_if_complete(message.bot, ts)


# ---------------- Ro'yxat ----------------

@router.message(Command("testlar"))
async def my_tests(message: Message):
    sets = await user_test_sets(message.from_user.id)
    if not sets:
        await message.answer("Hozircha testlaringiz yo'q. «✅ Test tayyorlash» bo'limidan boshlang.")
        return
    for ts in sets[:5]:
        parts = await set_parts(ts.id)
        if parts:
            await message.answer(f"📄 <b>{escape(ts.title)}</b>", reply_markup=set_menu_kb(ts, parts))


@router.callback_query(F.data.startswith("tset:"))
async def show_set(call: CallbackQuery):
    set_id = int(call.data.split(":")[1])
    async with Session() as s:
        ts = await s.get(TestSet, set_id)
    if not ts or ts.user_id != call.from_user.id:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.answer()
    parts = await set_parts(set_id)
    await call.message.answer(f"📄 <b>{escape(ts.title)}</b>", reply_markup=set_menu_kb(ts, parts))


# ---------------- Testni ishlash (quiz) ----------------

async def _ready_part(call: CallbackQuery) -> tuple[TestPart, TestSet] | None:
    part_id = int(call.data.split(":")[1])
    async with Session() as s:
        part = await s.get(TestPart, part_id)
        ts = await s.get(TestSet, part.set_id) if part else None
    if not part or ts.user_id != call.from_user.id:
        await call.answer("Topilmadi", show_alert=True)
        return
    if part.status == "waiting":
        await call.answer("🔒 Bu qism yopiq. «🔓 Hammasini ochish» tugmasi orqali to'lov qiling.", show_alert=True)
        return
    if part.status != "ready":
        await call.answer("⏳ Bu qism hali tayyorlanmoqda.", show_alert=True)
        return
    await call.answer()
    return part, ts


@router.callback_query(F.data.startswith("tpart:"))
async def part_menu(call: CallbackQuery):
    if not (found := await _ready_part(call)):
        return
    part, ts = found
    await call.message.answer(
        f"📝 <b>{escape(ts.part_title(part.number))}</b>\n"
        f"🖊 {len(part.questions)} ta savol · ⏱ har biriga {ts.time_limit} soniya\n\n"
        "👥 <b>Guruhda o'tkazish</b>: tugmani bosib guruhni tanlang — bot guruhga qo'shiladi va testni boshlash "
        "tugmasini yuboradi. Guruh a'zolari birga ishlaydi, oxirida reyting chiqadi.",
        reply_markup=part_menu_kb(part.id, ts.id, await group_quiz.group_link(call.bot, part.id)))


@router.callback_query(F.data.startswith("tgo:"))
async def start_part(call: CallbackQuery):
    if not (found := await _ready_part(call)):
        return
    part, ts = found
    await quiz.start(call.bot, quiz.QuizSession(
        user_id=call.from_user.id, title=ts.part_title(part.number), questions=part.questions,
        on_finish=_on_finish, time_limit=ts.time_limit or quiz.DEFAULT_TIME,
        meta={"part": part.id, "set": ts.id}))


async def _on_finish(s: quiz.QuizSession, bot):
    if s.idx == 0:
        await bot.send_message(s.user_id, "Test bekor qilindi.")
        return
    await bot.send_message(s.user_id, quiz.result_text(s, s.idx), protect_content=True,
                           reply_markup=after_test_kb(s.meta["part"], s.meta["set"]))
