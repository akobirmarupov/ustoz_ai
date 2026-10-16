"""Student: slayd, referat, mustaqil ish, maqola, kurs ishi."""
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data import config
from data.constants import BTN_MY_WORKS, BTN_STUDENT, DOC_BUTTONS, DOC_KINDS, ORDER_STATUS
from database.db import Session
from database.models import Order, User
from database.requests import enqueue, user_doc_orders, user_test_sets
from filters.filters import Registered
from keyboards.default.menu import cancel_menu, student_menu
from keyboards.inline.buttons import langs_kb, outline_kb, sizes_kb, skip_kb
from services import ai
from services.payments import money, start_payment
from states.states import DocOrder

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

MAX_OUTLINE_TRIES = 3


@router.message(F.text == BTN_STUDENT)
async def student_home(message: Message, state: FSMContext, db_user):
    await state.clear()
    left = max(0, config.FREE_DOCS - db_user.free_docs_used)
    await message.answer(
        "👨‍🎓 <b>Student bo'limi</b>\n\n"
        f"📊 Slayd, 📄 Referat, 📝 Mustaqil ish — {money(config.PRICES['slide'])}\n"
        f"📰 Maqola, 📚 Kurs ishi — {money(config.PRICES['maqola'])}\n"
        f"✅ Test tayyorlash — {money(config.PRICES['test_auto'])}\n\n"
        f"🎁 Sizda <b>{left}</b> ta bepul slayd/referat/mustaqil ish bor.",
        reply_markup=student_menu())


@router.message(F.text.in_(DOC_BUTTONS))
async def doc_start(message: Message, state: FSMContext):
    kind = DOC_BUTTONS[message.text]
    await state.clear()
    await state.update_data(kind=kind, tries=0)
    await state.set_state(DocOrder.topic)
    await message.answer(f"{DOC_KINDS[kind]['button']}\n\n✍️ Mavzuni yozing:", reply_markup=cancel_menu())


@router.message(DocOrder.topic, F.text)
async def doc_topic(message: Message, state: FSMContext):
    topic = message.text.strip()
    if len(topic) < 5:
        await message.answer("Mavzu juda qisqa. To'liqroq yozing:")
        return
    await state.update_data(topic=topic[:300])
    await state.set_state(DocOrder.lang)
    await message.answer("🌐 Qaysi tilda tayyorlansin?", reply_markup=langs_kb())


@router.callback_query(DocOrder.lang, F.data.startswith("lang:"))
async def doc_lang(call: CallbackQuery, state: FSMContext):
    await state.update_data(lang=call.data.split(":")[1])
    kind = (await state.get_data())["kind"]
    sizes = DOC_KINDS[kind]["sizes"]
    await call.answer()
    if len(sizes) == 1:
        await state.update_data(size=sizes[0][1])
        await _ask_titul(call.message, state, kind)
    else:
        await state.set_state(DocOrder.size)
        await call.message.edit_text("📏 Hajmini tanlang:", reply_markup=sizes_kb(kind))


@router.callback_query(DocOrder.size, F.data.startswith("size:"))
async def doc_size(call: CallbackQuery, state: FSMContext):
    await state.update_data(size=int(call.data.split(":")[1]))
    await call.answer()
    await _ask_titul(call.message, state, (await state.get_data())["kind"])


async def _ask_titul(message: Message, state: FSMContext, kind: str):
    await state.set_state(DocOrder.titul)
    if kind == "maqola":
        text = "✍️ Muallif ma'lumotlarini yozing (F.I.Sh., OTM, lavozim) — bitta qatorda:"
    else:
        text = ("🏷 Titul varag'i uchun har birini <b>yangi qatorda</b> yozing:\n"
                "1-qator: OTM nomi\n2-qator: Ismingiz (bajardi)\n3-qator: O'qituvchi (tekshirdi)")
    await message.answer(text, reply_markup=skip_kb())


@router.message(DocOrder.titul, F.text)
async def doc_titul(message: Message, state: FSMContext):
    lines = [ln.strip() for ln in message.text.split("\n") if ln.strip()][:3]
    await state.update_data(titul=[ln[:150] for ln in lines])
    await _make_outline(message, state)


@router.callback_query(DocOrder.titul, F.data == "titul:skip")
async def doc_titul_skip(call: CallbackQuery, state: FSMContext):
    await state.update_data(titul=[])
    await call.answer()
    await _make_outline(call.message, state)


async def _make_outline(message: Message, state: FSMContext):
    data = await state.get_data()
    wait = await message.answer("⏳ Reja tuzilmoqda...")
    try:
        outline = await ai.make_outline(data["kind"], data["topic"], data["lang"], data["size"])
    except ai.AIError as e:
        await wait.edit_text(f"⚠️ {e}. Mavzuni qayta yuboring yoki keyinroq urinib ko'ring.")
        await state.set_state(DocOrder.topic)
        return
    await state.update_data(outline=outline, tries=data.get("tries", 0) + 1)
    await state.set_state(DocOrder.outline)
    items = "\n".join(f"{i}. {escape(s)}" for i, s in enumerate(outline["sections"], 1))
    await wait.edit_text(f"📝 <b>{escape(outline['title'])}</b>\n\n{items}\n\nReja sizga ma'qulmi?",
                         reply_markup=outline_kb())


@router.callback_query(DocOrder.outline, F.data == "outline:again")
async def outline_again(call: CallbackQuery, state: FSMContext):
    if (await state.get_data()).get("tries", 0) >= MAX_OUTLINE_TRIES:
        await call.answer("Reja 3 marta qayta tuzildi. Mavzuni aniqroq yozib, qaytadan boshlang.", show_alert=True)
        return
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await _make_outline(call.message, state)


@router.callback_query(DocOrder.outline, F.data == "outline:cancel")
async def outline_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ Bekor qilindi.")
    await call.message.answer("Student bo'limi:", reply_markup=student_menu())


@router.callback_query(DocOrder.outline, F.data == "outline:ok")
async def outline_ok(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    kind = data["kind"]
    params = {k: data[k] for k in ("topic", "lang", "size", "titul", "outline")}

    async with Session() as s:
        user = await s.get(User, call.from_user.id)
        free = kind in config.FREE_DOC_KINDS and user.free_docs_used < config.FREE_DOCS
        if free:
            user.free_docs_used += 1
        order = Order(user_id=user.id, kind=kind, price=0 if free else config.PRICES[kind], is_free=free,
                      title=data["outline"]["title"][:250], params=params,
                      status="queued" if free else "awaiting_payment")
        s.add(order)
        await s.commit()

    if free:
        await enqueue("doc", order.id)
        await call.message.answer("🎁 Bepul buyurtma qabul qilindi! ⏳ Tayyorlanmoqda (odatda 1-5 daqiqa)...",
                                  reply_markup=student_menu())
    else:
        await call.message.answer("Buyurtma qabul qilindi ✅", reply_markup=student_menu())
        await start_payment(call.bot, user.id, "order", order.price,
                            f"{DOC_KINDS[kind]['title']}: {order.title}", order_id=order.id)


@router.message(F.text == BTN_MY_WORKS)
async def my_works(message: Message, db_user):
    orders = await user_doc_orders(db_user.id)
    sets = await user_test_sets(db_user.id)
    if not orders and not sets:
        await message.answer("Hozircha ishlaringiz yo'q.")
        return
    lines = [f"#{o.id} {DOC_KINDS[o.kind]['button']} {escape(o.title[:40])} — {ORDER_STATUS.get(o.status, o.status)}"
             for o in orders]
    text = "🗂 <b>Mening ishlarim</b>\n\n" + ("\n".join(lines) if lines else "Hujjatlar yo'q.")
    if sets:
        text += "\n\n✅ <b>Testlar</b> — ochish uchun: /testlar"
    await message.answer(text)


@router.message(DocOrder.topic)
@router.message(DocOrder.titul)
async def doc_expect_text(message: Message):
    await message.answer("Iltimos, matn ko'rinishida yozing.")
