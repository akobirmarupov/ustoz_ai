"""💰 Hisobim: balans, to'ldirish (karta), do'stni taklif qilish, kanal bonusi, hisobdan to'lash."""
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup, Message

from data import config
from data.constants import BTN_BALANCE, BTN_INVITE
from database.db import Session
from database.models import User
from database.requests import add_balance, balance_history, referral_stats
from filters.filters import Registered
from keyboards.default.menu import cancel_menu, main_menu
from services.payments import money, pay_from_balance, start_payment
from states.states import Topup

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

TX_ICON = {"topup": "💳", "referral": "🎁", "channel": "📢", "purchase": "🛒", "admin": "👑"}
_bot_username: str | None = None


async def bot_link(bot: Bot, user_id: int) -> str:
    global _bot_username
    if not _bot_username:
        _bot_username = (await bot.get_me()).username
    return f"https://t.me/{_bot_username}?start=ref_{user_id}"


def _channel_url() -> str:
    return f"https://t.me/{config.CHANNEL.lstrip('@')}"


async def _view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with Session() as s:
        user = await s.get(User, user_id)
    history = await balance_history(user_id, 5)
    lines = [f"{TX_ICON.get(t.kind, '•')} {'+' if t.amount > 0 else '−'}{money(abs(t.amount))} · {escape(t.note[:40])}"
             for t in history]
    text = (f"💰 <b>Hisobim</b>\n\nBalans: <b>{money(user.balance)}</b>\n\n"
            "Hisobdagi pul bilan Premium, slayd, referat, test va boshqa xizmatlarni to'laysiz "
            "(to'lov xabaridagi «💰 Hisobdan to'lash» tugmasi).\n"
            f"Pul topish: 🎁 do'st taklif qilish — har biri uchun <b>{money(config.REF_BONUS)}</b>"
            + ("" if user.channel_bonus else f", 📢 kanalga obuna — <b>{money(config.CHANNEL_BONUS)}</b>") + ".")
    if lines:
        text += "\n\n<b>So'nggi amallar:</b>\n" + "\n".join(lines)
    rows = [[B(text="➕ Hisobni to'ldirish", callback_data="bal:topup")],
            [B(text="🎁 Do'stni taklif qilish", callback_data="bal:invite")]]
    if not user.channel_bonus:
        rows.append([B(text=f"📢 Kanalga obuna (+{money(config.CHANNEL_BONUS)})", callback_data="bal:channel")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_BALANCE)
async def show(message: Message, state: FSMContext):
    await state.clear()
    text, kb = await _view(message.from_user.id)
    await message.answer(text, reply_markup=kb)


# ---------------- Do'stni taklif qilish ----------------

async def _invite_text(bot: Bot, user_id: int) -> str:
    link = await bot_link(bot, user_id)
    count, earned = await referral_stats(user_id)
    return (f"🎁 <b>Do'stlaringizni taklif qiling!</b>\n\n"
            f"Havolangiz orqali kirib, ro'yxatdan o'tgan har bir yangi do'st uchun hisobingizga "
            f"<b>{money(config.REF_BONUS)}</b> tushadi.\n\n"
            f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
            f"👥 Taklif qilganlaringiz: <b>{count}</b> ta · topilgan bonus: <b>{money(earned)}</b>\n\n"
            "Havolani do'stlaringizga, guruh va kanallarga yuboring 👇")


def _share_kb(link: str) -> InlineKeyboardMarkup:
    share = ("https://t.me/share/url?url=" + link +
             "&text=Ustoz%20Elite%20%E2%80%94%20testlar%2C%20mock%20imtihon%20va%20AI%20ustoz%20%F0%9F%8E%93")
    return InlineKeyboardMarkup(inline_keyboard=[[B(text="📤 Do'stlarga yuborish", url=share)]])


@router.message(F.text == BTN_INVITE)
async def invite_msg(message: Message):
    await message.answer(await _invite_text(message.bot, message.from_user.id),
                         reply_markup=_share_kb(await bot_link(message.bot, message.from_user.id)))


@router.callback_query(F.data == "bal:invite")
async def invite(call: CallbackQuery):
    await call.answer()
    await call.message.answer(await _invite_text(call.bot, call.from_user.id),
                              reply_markup=_share_kb(await bot_link(call.bot, call.from_user.id)))


# ---------------- Kanal bonusi ----------------

def _channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="📢 Kanalga o'tish", url=_channel_url())],
        [B(text="✅ Obuna bo'ldim — tekshirish", callback_data="bal:check")]])


@router.callback_query(F.data == "bal:channel")
async def channel(call: CallbackQuery):
    await call.answer()
    await call.message.answer(f"📢 {config.CHANNEL} kanaliga obuna bo'ling va «✅ Obuna bo'ldim» ni bosing — "
                              f"hisobingizga <b>{money(config.CHANNEL_BONUS)}</b> tushadi.", reply_markup=_channel_kb())


@router.callback_query(F.data == "bal:check")
async def channel_check(call: CallbackQuery):
    try:
        member = await call.bot.get_chat_member(config.CHANNEL, call.from_user.id)
    except TelegramAPIError:
        await call.answer("Tekshirib bo'lmadi. Admin botni kanalga admin qilib qo'shishi kerak.", show_alert=True)
        return
    if member.status not in ("member", "administrator", "creator"):
        await call.answer("Siz hali obuna bo'lmagansiz. Avval kanalga o'ting va obuna bo'ling.", show_alert=True)
        return
    async with Session() as s:  # bonus faqat bir marta
        user = await s.get(User, call.from_user.id)
        if user.channel_bonus:
            await call.answer("Bu bonus allaqachon olingan ✅", show_alert=True)
            return
        user.channel_bonus = True
        await s.commit()
    balance = await add_balance(call.from_user.id, config.CHANNEL_BONUS, "channel", f"{config.CHANNEL} ga obuna")
    await call.answer("✅ Bonus qo'shildi!")
    await call.message.edit_text(f"🎉 Rahmat! Hisobingizga <b>{money(config.CHANNEL_BONUS)}</b> qo'shildi.\n"
                                 f"💰 Balans: <b>{money(balance)}</b>")


# ---------------- Hisobni to'ldirish ----------------

@router.callback_query(F.data == "bal:topup")
async def topup(call: CallbackQuery, state: FSMContext):
    await state.set_state(Topup.amount)
    await call.answer()
    rows = [[B(text=money(a), callback_data=f"top:{a}") for a in config.TOPUP_AMOUNTS[i:i + 2]]
            for i in range(0, len(config.TOPUP_AMOUNTS), 2)]
    await call.message.answer("➕ Qancha summaga to'ldirasiz? Tanlang yoki summani raqam bilan yozing "
                              f"({money(config.MIN_TOPUP)} dan):", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.message.answer("Summa kutilmoqda...", reply_markup=cancel_menu())


async def _create_topup(bot: Bot, user_id: int, amount: int):
    await start_payment(bot, user_id, "topup", amount, "💰 Hisobni to'ldirish")
    await bot.send_message(user_id, "Admin chekni tasdiqlagach, pul hisobingizga tushadi.", reply_markup=main_menu())


@router.callback_query(Topup.amount, F.data.startswith("top:"))
async def topup_pick(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await _create_topup(call.bot, call.from_user.id, int(call.data.split(":")[1]))


@router.message(Topup.amount, F.text)
async def topup_typed(message: Message, state: FSMContext):
    digits = "".join(ch for ch in message.text if ch.isdigit())
    amount = int(digits) if digits else 0
    if not config.MIN_TOPUP <= amount <= config.MAX_TOPUP:
        await message.answer(f"Summa {money(config.MIN_TOPUP)} dan {money(config.MAX_TOPUP)} gacha bo'lsin. Qaytadan yozing:")
        return
    await state.clear()
    await _create_topup(message.bot, message.from_user.id, amount)


# ---------------- Hisobdan to'lash ----------------

@router.callback_query(F.data.startswith("paybal:"))
async def pay_balance(call: CallbackQuery):
    ok, msg = await pay_from_balance(call.bot, int(call.data.split(":")[1]), call.from_user.id)
    if not ok:
        await call.answer(msg, show_alert=True)
        return
    await call.answer("✅ Hisobdan to'landi")
    await call.message.edit_reply_markup(reply_markup=None)
