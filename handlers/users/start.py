import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy import func, select

from data import config
from database.db import Session
from database.models import ReferralClick, User
from database.requests import add_balance, create_user, referral_bonuses_today
from keyboards.default.menu import main_menu, phone_menu
from states.states import Register

router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, command: CommandObject, db_user=None):
    await state.clear()
    ref = command.args or ""
    if not db_user and ref.startswith("ref_") and ref[4:].isdigit() and int(ref[4:]) != message.from_user.id:
        async with Session() as s:  # bonus faqat ro'yxatdan to'liq o'tgandan keyin beriladi
            await s.merge(ReferralClick(user_id=message.from_user.id, ref_id=int(ref[4:])))
            await s.commit()
    if db_user:
        await message.answer(f"Assalomu alaykum, {escape(db_user.full_name)}! 👋\nBo'limni tanlang:",
                             reply_markup=main_menu())
        return
    await message.answer("Assalomu alaykum! <b>Ustoz Elite</b> botiga xush kelibsiz 🎓\n\n"
                         "Ro'yxatdan o'tish uchun ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Register.name)


async def _reward_referrer(bot: Bot, ref_id: int | None, new_user: User, phone: str):
    """Taklif bonusi: taklif qiluvchi mavjud, raqam yangi va kunlik limitdan oshmagan bo'lsa."""
    if not ref_id:
        return
    async with Session() as s:
        referrer = await s.get(User, ref_id)
        same_phone = (await s.execute(select(func.count(User.id)).where(User.phone == phone))).scalar_one()
        if not referrer or referrer.is_blocked or same_phone > 1:
            return
        (await s.get(User, new_user.id)).referred_by = ref_id
        await s.commit()
    if await referral_bonuses_today(ref_id) >= config.REF_DAILY_LIMIT:
        return
    balance = await add_balance(ref_id, config.REF_BONUS, "referral", f"Do'st: {new_user.full_name}")
    try:
        await bot.send_message(ref_id, f"🎉 Do'stingiz <b>{escape(new_user.full_name)}</b> qo'shildi!\n"
                                       f"Hisobingizga <b>{config.REF_BONUS:,} so'm</b> tushdi.".replace(",", " ") +
                               f"\n💰 Balans: <b>{balance:,} so'm</b>".replace(",", " "))
    except TelegramAPIError:
        logging.getLogger(__name__).info("Taklif qiluvchiga xabar yuborilmadi: %s", ref_id)


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
    phone = message.contact.phone_number
    user = await create_user(message.from_user.id, data["name"], message.from_user.username, phone)
    await state.clear()
    async with Session() as s:
        click = await s.get(ReferralClick, user.id)
        ref_id = click.ref_id if click else None
        if click:
            await s.delete(click)
            await s.commit()
    await _reward_referrer(message.bot, ref_id, user, phone)
    await message.answer(
        "✅ Ro'yxatdan o'tdingiz!\n\n"
        "🎓 <b>Abituriyent</b> — imtihonga tayyorgarlik va AI ustoz\n"
        "👨‍🎓 <b>Student</b> — slayd, referat, mustaqil ish, esse, maqola, kurs ishi va testlar\n\n"
        "🎁 Sovg'a: 2 ta bepul slayd/referat/mustaqil ish va 1 ta bepul test!",
        reply_markup=main_menu())


@router.message(Register.phone)
async def reg_phone_wrong(message: Message):
    await message.answer("Raqamni «📱 Raqamni yuborish» tugmasi orqali yuboring.", reply_markup=phone_menu())
