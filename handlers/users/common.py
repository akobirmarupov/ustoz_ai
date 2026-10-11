from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from data import config
from data.constants import BTN_BACK, BTN_CANCEL, BTN_HELP, BTN_PAYMENTS, BTN_PROFILE
from database.requests import effective_plan, today_usage, user_payments
from filters.filters import Registered
from keyboards.default.menu import main_menu
from services.payments import money

router = Router()
router.message.filter(Registered())

PAY_STATUS = {"waiting_receipt": "💳 Chek kutilmoqda", "pending": "⏳ Tekshirilmoqda",
              "approved": "✅ Tasdiqlangan", "rejected": "❌ Rad etilgan"}


@router.message(F.text.in_({BTN_BACK, BTN_CANCEL}))
async def back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bosh menyu:", reply_markup=main_menu())


@router.message(F.text == BTN_PROFILE)
async def profile(message: Message, db_user):
    plan = effective_plan(db_user)
    until = f" ({db_user.plan_until:%d.%m.%Y} gacha)" if plan != "free" else ""
    free_docs = max(0, config.FREE_DOCS - db_user.free_docs_used)
    limit = config.PLANS[plan]["tests"]
    used = await today_usage(db_user.id, "tests")
    tests_today = f"{used} / {limit}" if limit is not None else f"{used} (cheksiz)"
    await message.answer(
        f"👤 <b>{escape(db_user.full_name)}</b>\n"
        f"📱 {db_user.phone}\n"
        f"🆔 <code>{db_user.id}</code>\n\n"
        f"⭐️ Tarif: <b>{config.PLANS[plan]['name']}</b>{until}\n"
        f"📝 Bugun ishlangan testlar: <b>{tests_today}</b>\n"
        f"🎁 Bepul slayd/referat/mustaqil ish: <b>{free_docs}</b> ta\n"
        f"🎁 Bepul test: <b>{'ishlatilgan' if db_user.free_test_used else '1 ta bor'}</b>")


@router.message(F.text == BTN_PAYMENTS)
async def payments(message: Message, db_user):
    items = await user_payments(db_user.id)
    if not items:
        await message.answer("Hozircha to'lovlar yo'q.")
        return
    lines = [f"#{p.id} · {money(p.amount)} · {PAY_STATUS.get(p.status, p.status)} · {p.created_at:%d.%m %H:%M}"
             for p in items]
    await message.answer("💳 <b>So'nggi to'lovlar</b>\n\n" + "\n".join(lines))


@router.message(F.text == BTN_HELP)
async def help_(message: Message):
    support = f"\n\n✉️ Savol va takliflar: @{config.SUPPORT_USERNAME}" if config.SUPPORT_USERNAME else ""
    await message.answer(
        "ℹ️ <b>Ustoz Elite</b> qanday ishlaydi\n\n"
        "1. Bo'limni tanlang va so'ralgan ma'lumotlarni kiriting.\n"
        "2. Pullik xizmatda kartaga to'lab, izohga kodni yozing.\n"
        "3. «✅ To'lov qildim» tugmasini bosib, chek rasmini yuboring.\n"
        "4. Admin tasdiqlagach, ishingiz avtomatik tayyorlanadi.\n\n"
        "🎓 <b>Abituriyent:</b> 📝 Test ishlash, 🧪 Mock imtihon, ❌ Xatolar daftari, 🏆 Reyting, 🤖 AI ustoz.\n"
        "👨‍🎓 <b>Student:</b> slayd, referat, mustaqil ish, maqola, kurs ishi va test tayyorlash." + support)
