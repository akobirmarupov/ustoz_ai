"""Chek orqali to'lov: ko'rsatma yuborish, adminga xabar, tasdiqlash va rad etish."""
import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update

from data import config
from data.constants import KIND_TITLES
from database.db import Session
from database.models import BalanceTx, Order, Payment, TestPart, TestSet, User
from database.requests import add_balance, enqueue, new_payment, open_payment_for_order, spend_balance
from keyboards.inline.buttons import admin_payment_kb, paid_kb

log = logging.getLogger(__name__)


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


def payment_title(payment: Payment, order: Order | None) -> str:
    if payment.purpose == "topup":
        return "💰 Hisobni to'ldirish"
    if payment.purpose == "premium":
        return f"⭐️ Premium {config.PLANS[payment.plan]['name']} ({config.PLAN_DAYS} kun)"
    title = KIND_TITLES.get(order.kind, order.kind) if order else "Buyurtma"
    return f"{title}: {order.title}" if order and order.title else title


async def send_instruction(bot: Bot, payment: Payment, title: str, note: str = ""):
    owner = f"Egasi: {escape(config.CARD_OWNER)}\n" if config.CARD_OWNER else ""
    text = (f"{note}💳 <b>To'lov</b>\n\n"
            f"Xizmat: <b>{escape(title)}</b>\n"
            f"Summa: <b>{money(payment.amount)}</b>\n\n"
            f"Karta: <code>{config.CARD_NUMBER}</code>\n{owner}\n"
            f"❗️ To'lov izohiga shu kodni yozing: <code>{payment.code}</code>\n\n"
            "To'lovdan so'ng «✅ To'lov qildim» tugmasini bosing va chek rasmini yuboring.")
    kb = paid_kb(payment.id)
    if payment.purpose != "topup":
        async with Session() as s:
            balance = (await s.get(User, payment.user_id)).balance
        text += f"\n\n💰 Yoki hisobingizdan to'lang (balans: <b>{money(balance)}</b>)."
        kb = InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [[InlineKeyboardButton(
            text=f"💰 Hisobdan to'lash ({money(balance)})", callback_data=f"paybal:{payment.id}")]])
    await bot.send_message(payment.user_id, text, reply_markup=kb)


async def pay_from_balance(bot: Bot, payment_id: int, user_id: int) -> tuple[bool, str]:
    """Hisobdan to'lash: balans yetsa yechiladi va xizmat admin tasdig'isiz darhol ochiladi."""
    async with Session() as s:
        p = await s.get(Payment, payment_id)
        order = await s.get(Order, p.order_id) if p and p.order_id else None
    if not p or p.user_id != user_id or p.purpose == "topup":
        return False, "To'lov topilmadi"
    # To'lovni atomik «band qilamiz»: ikki marta bosilsa ham faqat bittasi o'tadi
    async with Session() as s:
        res = await s.execute(update(Payment).where(Payment.id == payment_id, Payment.status == "waiting_receipt")
                              .values(status="pending", method="balance"))
        await s.commit()
    if res.rowcount != 1:
        return False, "Bu to'lov allaqachon bajarilgan yoki tekshirilmoqda"
    if not await spend_balance(user_id, p.amount, payment_title(p, order)):
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment_id)
                            .values(status="waiting_receipt", method="manual"))
            await s.commit()
        return False, "Hisobingizda mablag' yetarli emas. «💰 Hisobim» → «➕ Hisobni to'ldirish»"
    ok, msg = await approve(bot, payment_id, admin_id=0)
    if not ok:  # kutilmagan holat: pul qaytariladi
        await add_balance(user_id, p.amount, "purchase", "Qaytarildi: " + payment_title(p, order))
    return ok, msg


async def start_payment(bot: Bot, user_id: int, purpose: str, amount: int, title: str,
                        order_id: int | None = None, plan: str | None = None) -> Payment:
    if order_id:
        existing = await open_payment_for_order(order_id)
        if existing:
            await send_instruction(bot, existing, title)
            return existing
        async with Session() as s:
            order = await s.get(Order, order_id)
            order.status = "awaiting_payment"
            await s.commit()
    payment = await new_payment(user_id, purpose, amount, order_id=order_id, plan=plan)
    await send_instruction(bot, payment, title)
    return payment


async def notify_admins(bot: Bot, payment: Payment, user: User, title: str):
    uname = f" @{user.username}" if user.username else ""
    caption = (f"🧾 <b>Yangi to'lov #{payment.id}</b>\n\n"
               f"👤 {escape(user.full_name)}{uname} (<code>{user.id}</code>)\n"
               f"📱 {user.phone or '-'}\n"
               f"🛒 {escape(title)}\n"
               f"💰 {money(payment.amount)}\n"
               f"🔑 Kod: <code>{payment.code}</code>")
    for admin in config.ADMINS:
        try:
            if payment.receipt_type == "photo":
                await bot.send_photo(admin, payment.receipt_file_id, caption=caption,
                                     reply_markup=admin_payment_kb(payment.id))
            else:
                await bot.send_document(admin, payment.receipt_file_id, caption=caption,
                                        reply_markup=admin_payment_kb(payment.id))
        except TelegramAPIError as e:
            log.warning("Adminga (%s) xabar yuborilmadi: %s", admin, e)


async def approve(bot: Bot, payment_id: int, admin_id: int) -> tuple[bool, str]:
    jobs: list[tuple[str, int]] = []
    finished_set = None
    follow_kb = None
    async with Session() as s:
        p = await s.get(Payment, payment_id)
        if not p or p.status != "pending":
            return False, "Bu to'lov allaqachon ko'rib chiqilgan"
        now = datetime.now()
        p.status, p.admin_id, p.decided_at = "approved", admin_id, now
        user = await s.get(User, p.user_id)
        if p.purpose == "topup":
            user.balance += p.amount
            s.add(BalanceTx(user_id=user.id, amount=p.amount, kind="topup", note=f"Karta orqali · {p.code}"))
            msg = f"✅ Hisobingiz <b>{money(p.amount)}</b> ga to'ldirildi!\n💰 Balans: <b>{money(user.balance)}</b>"
        elif p.purpose == "premium":
            start = user.plan_until if (user.plan == p.plan and user.plan_until and user.plan_until > now) else now
            user.plan = p.plan
            user.plan_until = start + timedelta(days=config.PLAN_DAYS)
            user.plan_reminded = False
            msg = (f"✅ To'lov tasdiqlandi!\n\n⭐️ <b>{config.PLANS[p.plan]['name']}</b> tarifi "
                   f"<b>{user.plan_until:%d.%m.%Y}</b> gacha faollashtirildi. Omad! 🚀")
        else:
            order = await s.get(Order, p.order_id)
            ts = (await s.execute(select(TestSet).where(TestSet.order_id == order.id))).scalars().first() \
                if order.kind == "test" else None
            if order.kind == "test" and ts is None:  # yangi tartib: to'lov oldin, fayl/savollar keyin
                order.status = "paid"
                manual = order.params.get("source") == "manual"
                msg = "✅ To'lov tasdiqlandi! Endi " + ("savollarni yozing 👇" if manual else "faylni yuboring 👇")
                follow_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text="✍️ Savollarni yozish" if manual else "📎 Faylni yuborish", callback_data=f"tstart:{order.id}")]])
            elif order.kind == "test":
                ts.unlocked = True
                parts = (await s.execute(select(TestPart).where(
                    TestPart.set_id == ts.id, TestPart.status == "waiting"))).scalars().all()
                if ts.source in ("auto", "manual"):  # savollar tayyor, AI kerak emas
                    for part in parts:
                        part.status = "ready"
                    finished_set = ts
                    msg = "✅ To'lov tasdiqlandi!"
                else:
                    for part in parts:
                        part.status = "queued"
                        jobs.append(("test_part", part.id))
                    msg = "✅ To'lov tasdiqlandi! Qolgan testlar tayyorlanmoqda, tayyor bo'lgach xabar beraman."
                order.status = "processing"
            else:
                order.status = "queued"
                jobs.append(("doc", order.id))
                msg = "✅ To'lov tasdiqlandi! Ishingiz tayyorlanmoqda (odatda 1-5 daqiqa)."
        await s.commit()
    for kind, ref in jobs:
        await enqueue(kind, ref)
    try:
        await bot.send_message(p.user_id, msg, reply_markup=follow_kb)
    except TelegramAPIError:
        pass
    if finished_set:
        from services.worker import _finish_if_complete  # aylana importdan qochish uchun
        await _finish_if_complete(bot, finished_set)
    return True, "Tasdiqlandi"


async def reject(bot: Bot, payment_id: int, admin_id: int, reason: str) -> tuple[bool, str]:
    async with Session() as s:
        p = await s.get(Payment, payment_id)
        if not p or p.status != "pending":
            return False, "Bu to'lov allaqachon ko'rib chiqilgan"
        p.status, p.admin_id, p.decided_at, p.reject_reason = "rejected", admin_id, datetime.now(), reason
        order = await s.get(Order, p.order_id) if p.order_id else None
        if order:
            order.status = "awaiting_payment"
        await s.commit()
    title = payment_title(p, order)
    retry = await new_payment(p.user_id, p.purpose, p.amount, order_id=p.order_id, plan=p.plan)
    try:
        await send_instruction(bot, retry, title,
                               note=f"❌ To'lovingiz rad etildi.\nSabab: <b>{escape(reason)}</b>\n\n"
                                    "Qayta to'lash uchun:\n\n")
    except TelegramAPIError:
        pass
    return True, "Rad etildi"
