"""Admin: barcha foydalanuvchilarga xabar yuborish."""
import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.requests import all_user_ids
from filters.filters import IsAdmin
from states.states import Broadcast

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("xabar"))
async def start(message: Message, state: FSMContext):
    await state.set_state(Broadcast.message)
    await message.answer("📢 Hammaga yuboriladigan xabarni yuboring (matn, rasm, video — istalgan ko'rinishda).\n"
                         "Bekor qilish: /admin")


@router.message(Broadcast.message)
async def got(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    n = len(await all_user_ids())
    await message.answer(f"Bu xabar <b>{n}</b> ta foydalanuvchiga yuboriladi. Yuboraymi?",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                             InlineKeyboardButton(text="✅ Yuborish", callback_data="bc:yes"),
                             InlineKeyboardButton(text="❌ Bekor", callback_data="bc:no")]]))


@router.callback_query(Broadcast.confirm, F.data.startswith("bc:"))
async def confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    if call.data == "bc:no":
        await call.message.edit_text("❌ Bekor qilindi.")
        return
    await call.message.edit_text("⏳ Yuborilmoqda...")
    ok = fail = 0
    for uid in await all_user_ids():
        try:
            await call.bot.copy_message(uid, data["chat_id"], data["message_id"])
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await call.bot.copy_message(uid, data["chat_id"], data["message_id"])
                ok += 1
            except TelegramAPIError:
                fail += 1
        except TelegramAPIError:
            fail += 1  # botni bloklagan foydalanuvchilar
        await asyncio.sleep(0.05)  # Telegram limiti: soniyasiga ~20 ta xabar
    await call.message.answer(f"✅ Yuborildi: {ok} ta\n⚠️ Yetib bormadi: {fail} ta (botni bloklaganlar)")
