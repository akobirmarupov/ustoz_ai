"""Admin: to'lovlarni tasdiqlash, statistika, qo'lda Premium berish."""
from datetime import datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from data import config
from database.db import Session
from database.models import Order, User
from database.requests import pending_payments, stats
from filters.filters import IsAdmin
from keyboards.inline.buttons import REJECT_REASONS, admin_payment_kb
from services import payments
from services.payments import money
from states.states import AdminReject

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("admin"))
async def panel(message: Message):
    st = await stats()
    await message.answer(
        "🛠 <b>Admin panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{st['users']}</b> (bugun +{st['new_today']})\n"
        f"⭐️ Faol Premium: <b>{st['premium']}</b>\n"
        f"⏳ Kutilayotgan to'lovlar: <b>{st['pending']}</b>\n"
        f"⚙️ Navbatdagi ishlar: <b>{st['queued']}</b>\n\n"
        f"💰 Bugun: <b>{money(st['revenue_today'])}</b>\n"
        f"💰 Shu oy: <b>{money(st['revenue_month'])}</b>\n\n"
        "Buyruqlar:\n"
        "/sinflar — sinflar, fanlar, testlar va mock imtihonlar\n"
        "/xabar — barcha foydalanuvchilarga xabar yuborish\n"
        "/tolovlar — kutilayotgan to'lovlar\n"
        "/premium ID tarif kun — qo'lda Premium berish (tarif: basic, pro, max)\n"
        "/block ID, /unblock ID",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 Sinflar va fanlar", callback_data="cg:list")]]))


@router.message(Command("tolovlar"))
async def pending(message: Message):
    items = await pending_payments()
    if not items:
        await message.answer("Kutilayotgan to'lovlar yo'q ✅")
        return
    for p in items:
        async with Session() as s:
            user = await s.get(User, p.user_id)
            order = await s.get(Order, p.order_id) if p.order_id else None
        caption = (f"🧾 #{p.id} · {escape(user.full_name)} (<code>{user.id}</code>)\n"
                   f"🛒 {escape(payments.payment_title(p, order))}\n💰 {money(p.amount)} · 🔑 {p.code}")
        send = message.answer_photo if p.receipt_type == "photo" else message.answer_document
        await send(p.receipt_file_id, caption=caption, reply_markup=admin_payment_kb(p.id))


async def _mark(call: CallbackQuery, text: str):
    base = call.message.caption or call.message.text or ""
    await call.message.edit_caption(caption=f"{base}\n\n{text}", reply_markup=None)


@router.callback_query(F.data.startswith("adm:ok:"))
async def approve(call: CallbackQuery):
    payment_id = int(call.data.split(":")[2])
    ok, msg = await payments.approve(call.bot, payment_id, call.from_user.id)
    await call.answer(msg, show_alert=not ok)
    if ok:
        await _mark(call, f"✅ Tasdiqlandi — {escape(call.from_user.full_name)}")


@router.callback_query(F.data.startswith("adm:no:"))
async def reject(call: CallbackQuery, state: FSMContext):
    _, _, payment_id, code = call.data.split(":")
    if code == "custom":
        await state.set_state(AdminReject.reason)
        await state.update_data(payment_id=int(payment_id), msg_chat=call.message.chat.id,
                                msg_id=call.message.message_id)
        await call.answer()
        await call.message.answer("✍️ Rad etish sababini yozing:")
        return
    ok, msg = await payments.reject(call.bot, int(payment_id), call.from_user.id, REJECT_REASONS[code])
    await call.answer(msg, show_alert=not ok)
    if ok:
        await _mark(call, f"❌ Rad etildi: {REJECT_REASONS[code]}")


@router.message(AdminReject.reason, F.text)
async def reject_custom(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    ok, msg = await payments.reject(message.bot, data["payment_id"], message.from_user.id, message.text[:300])
    await message.answer(("❌ " if ok else "") + msg)


@router.message(Command("premium"))
async def give_premium(message: Message, command: CommandObject):
    try:
        uid, plan, days = command.args.split()
        uid, days = int(uid), int(days)
        assert plan in ("basic", "pro", "max")
    except (AttributeError, ValueError, AssertionError):
        await message.answer("Format: /premium 123456789 pro 30")
        return
    async with Session() as s:
        user = await s.get(User, uid)
        if not user:
            await message.answer("Foydalanuvchi topilmadi")
            return
        user.plan, user.plan_until, user.plan_reminded = plan, datetime.now() + timedelta(days=days), False
        await s.commit()
    await message.answer(f"✅ {escape(user.full_name)} ga {config.PLANS[plan]['name']} {days} kunga berildi.")
    await message.bot.send_message(uid, f"🎁 Sizga <b>{config.PLANS[plan]['name']}</b> tarifi "
                                        f"{user.plan_until:%d.%m.%Y} gacha berildi!")


@router.message(Command("block", "unblock"))
async def block(message: Message, command: CommandObject):
    try:
        uid = int(command.args)
    except (TypeError, ValueError):
        await message.answer("Format: /block 123456789")
        return
    async with Session() as s:
        user = await s.get(User, uid)
        if not user:
            await message.answer("Foydalanuvchi topilmadi")
            return
        user.is_blocked = command.command == "block"
        await s.commit()
    await message.answer("✅ Bajarildi")
