from aiogram import Router
from aiogram.types import CallbackQuery, Message

from keyboards.default.menu import main_menu

router = Router()


@router.message()
async def unknown(message: Message, db_user=None):
    if not db_user:
        await message.answer("Botdan foydalanish uchun /start ni bosing.")
        return
    await message.answer("Quyidagi menyudan tanlang 👇", reply_markup=main_menu())


@router.callback_query()
async def unknown_callback(call: CallbackQuery, db_user=None):
    await call.answer("Bu tugma eskirgan. Menyudan qaytadan tanlang." if db_user else "Avval /start ni bosing.",
                      show_alert=True)
