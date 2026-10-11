"""Foydalanuvchi chekni yuborishi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from database.db import Session
from database.models import Order, Payment, User
from filters.filters import Registered
from keyboards.default.menu import cancel_menu, main_menu
from services.payments import notify_admins, payment_title
from states.states import Receipt

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())


@router.callback_query(F.data.startswith("paid:"))
async def paid(call: CallbackQuery, state: FSMContext):
    payment_id = int(call.data.split(":")[1])
    async with Session() as s:
        p = await s.get(Payment, payment_id)
    if not p or p.user_id != call.from_user.id:
        await call.answer("To'lov topilmadi", show_alert=True)
        return
    if p.status != "waiting_receipt":
        await call.answer("Bu to'lov uchun chek allaqachon yuborilgan.", show_alert=True)
        return
    await call.answer()
    await state.set_state(Receipt.wait)
    await state.update_data(payment_id=payment_id)
    await call.message.answer("🧾 Chek rasmini (skrinshot) yoki PDF faylini yuboring:", reply_markup=cancel_menu())


@router.message(Receipt.wait, F.photo | F.document)
async def receipt(message: Message, state: FSMContext):
    if message.photo:
        file_id, unique_id, rtype = message.photo[-1].file_id, message.photo[-1].file_unique_id, "photo"
    else:
        file_id, unique_id, rtype = message.document.file_id, message.document.file_unique_id, "document"
    payment_id = (await state.get_data())["payment_id"]

    async with Session() as s:
        p = await s.get(Payment, payment_id)
        if p.status != "waiting_receipt":
            await state.clear()
            await message.answer("Bu to'lov uchun chek allaqachon yuborilgan.", reply_markup=main_menu())
            return
        p.receipt_file_id, p.receipt_unique_id, p.receipt_type, p.status = file_id, unique_id, rtype, "pending"
        order = await s.get(Order, p.order_id) if p.order_id else None
        if order:
            order.status = "payment_review"
        user = await s.get(User, p.user_id)
        try:
            await s.commit()
        except IntegrityError:
            await message.answer("⚠️ Bu chek avval yuborilgan. Iltimos, shu to'lovning o'z chekini yuboring.")
            return

    await state.clear()
    await message.answer("✅ Chek qabul qilindi! Admin tekshirgach darhol xabar beramiz (odatda 5-30 daqiqa).",
                         reply_markup=main_menu())
    await notify_admins(message.bot, p, user, payment_title(p, order))


@router.message(Receipt.wait)
async def receipt_wrong(message: Message):
    await message.answer("Iltimos, chek rasmini yoki PDF faylini yuboring.")
