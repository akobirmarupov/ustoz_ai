"""Abituriyent bo'limi: AI ustoz va Premium. O'quv qismlari keyingi bosqichda qo'shiladi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data import config
from data.constants import ABITURIYENT_SOON, BTN_ABITURIYENT, BTN_PREMIUM, BTN_TUTOR, SUBJECTS
from database.requests import effective_plan, refund_quota, use_quota
from filters.filters import Registered
from keyboards.default.menu import abituriyent_menu
from keyboards.inline.buttons import plans_kb, subjects_kb
from services import ai
from services.payments import start_payment
from states.states import Tutor

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

HISTORY = 8  # AI ustoz eslab qoladigan oxirgi xabarlar soni

PLANS_TEXT = (
    "⭐️ <b>Premium tariflar</b> (30 kun)\n\n"
    "🆓 <b>Bepul</b> — kuniga 3 ta test, 3 ta AI savol, oyiga 1 ta mock\n\n"
    "🔹 <b>Basic — 20 000 so'm</b>\n"
    "Kuniga 5 ta test, 15 ta AI savol, haftasiga 1 ta mock, oyiga 10 ta test yaratish\n\n"
    "⭐️ <b>Pro — 30 000 so'm</b> (eng ommabop)\n"
    "Kuniga 9 ta test, 40 ta AI savol, haftasiga 3 ta mock, oyiga 20 ta test yaratish\n\n"
    "💎 <b>Max Pro — 40 000 so'm</b>\n"
    "Cheksiz test, cheksiz AI savol, cheksiz mock, oyiga 30 ta test yaratish"
)


@router.message(F.text == BTN_ABITURIYENT)
async def home(message: Message, state: FSMContext, db_user):
    await state.clear()
    plan = config.PLANS[effective_plan(db_user)]["name"]
    await message.answer(f"🎓 <b>Abituriyent bo'limi</b>\nTarifingiz: <b>{plan}</b>",
                         reply_markup=abituriyent_menu())


@router.message(F.text.in_(ABITURIYENT_SOON))
async def soon(message: Message):
    await message.answer("🚧 Bu bo'lim tayyorlanmoqda va tez orada ishga tushadi!\n\n"
                         "Hozircha «🤖 AI ustozga savol» bo'limidan foydalanishingiz mumkin.")


# ---------------- Premium ----------------

@router.message(F.text == BTN_PREMIUM)
async def premium(message: Message, db_user):
    plan = effective_plan(db_user)
    current = (f"\n\nHozirgi tarif: <b>{config.PLANS[plan]['name']}</b> ({db_user.plan_until:%d.%m.%Y} gacha)"
               if plan != "free" else "")
    await message.answer(PLANS_TEXT + current, reply_markup=plans_kb())


@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(call: CallbackQuery):
    code = call.data.split(":")[1]
    plan = config.PLANS[code]
    await call.answer()
    await start_payment(call.bot, call.from_user.id, "premium", plan["price"],
                        f"⭐️ Premium {plan['name']} ({config.PLAN_DAYS} kun)", plan=code)


# ---------------- AI ustoz ----------------

@router.message(F.text == BTN_TUTOR)
async def tutor_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🤖 Qaysi fan bo'yicha savolingiz bor?", reply_markup=subjects_kb())


@router.callback_query(F.data.startswith("subj:"))
async def tutor_subject(call: CallbackQuery, state: FSMContext):
    code = call.data.split(":")[1]
    await state.set_state(Tutor.chat)
    await state.update_data(subject=code, history=[])
    await call.answer()
    await call.message.edit_text(f"🤖 <b>{SUBJECTS[code]}</b> bo'yicha savolingizni yozing.\n"
                                 "Chiqish uchun «⬅️ Bosh menyu» ni bosing.")


@router.message(Tutor.chat, F.text)
async def tutor_chat(message: Message, state: FSMContext, db_user):
    plan = effective_plan(db_user)
    limit = config.PLANS[plan]["ai_chat"]
    ok, _ = await use_quota(db_user.id, "ai_chat", limit if limit is not None else config.AI_FAIR_USE)
    if not ok:
        await message.answer(f"⏳ Bugungi limit tugadi ({limit or config.AI_FAIR_USE} ta savol).\n"
                             "Ertaga davom eting yoki tarifni oshiring 🚀", reply_markup=plans_kb())
        return
    data = await state.get_data()
    history = data.get("history", []) + [{"role": "user", "content": message.text[:2000]}]
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = await ai.tutor_reply(SUBJECTS[data["subject"]], history[-HISTORY:])
    except ai.AIError as e:
        await refund_quota(db_user.id, "ai_chat")
        await message.answer(f"⚠️ {e}")
        return
    history.append({"role": "assistant", "content": reply})
    await state.update_data(history=history[-HISTORY:])
    for i in range(0, len(reply), 4000):
        await message.answer(reply[i:i + 4000], parse_mode=None)
