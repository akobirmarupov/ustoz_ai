from html import escape

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from database.requests import create_user
from keyboards.default.menu import main_menu, phone_menu
from states.states import Register

router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db_user=None):
    await state.clear()
    if db_user:
        await message.answer(f"Assalomu alaykum, {escape(db_user.full_name)}! 👋\nBo'limni tanlang:",
                             reply_markup=main_menu())
        return
    await message.answer("Assalomu alaykum! <b>Ustoz Elite</b> botiga xush kelibsiz 🎓\n\n"
                         "Ro'yxatdan o'tish uchun ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Register.name)


@router.message(Register.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()[:64]
    if len(name) < 2 or name.startswith("/"):
        await message.answer("Iltimos, ismingizni to'g'ri kiriting:")
        return
    await state.update_data(name=name)
    await message.answer("📱 Telefon raqamingizni pastdagi tugma orqali yuboring:", reply_markup=phone_menu())
    await state.set_state(Register.phone)


@router.message(Register.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o'zingizning raqamingizni tugma orqali yuboring.")
        return
    data = await state.get_data()
    await create_user(message.from_user.id, data["name"], message.from_user.username, message.contact.phone_number)
    await state.clear()
    await message.answer(
        "✅ Ro'yxatdan o'tdingiz!\n\n"
        "🎓 <b>Abituriyent</b> — imtihonga tayyorgarlik va AI ustoz\n"
        "👨‍🎓 <b>Student</b> — slayd, referat, mustaqil ish, maqola, kurs ishi va testlar\n\n"
        "🎁 Sovg'a: 2 ta bepul slayd/referat/mustaqil ish va 1 ta bepul test!",
        reply_markup=main_menu())


@router.message(Register.phone)
async def reg_phone_wrong(message: Message):
    await message.answer("Raqamni «📱 Raqamni yuborish» tugmasi orqali yuboring.", reply_markup=phone_menu())
