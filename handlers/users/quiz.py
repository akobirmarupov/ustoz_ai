"""Quiz javoblari va «Testni yakunlash» tugmasi."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, PollAnswer

from services import group_quiz, quiz

router = Router()


@router.poll_answer()
async def poll_answer(answer: PollAnswer, bot: Bot):
    if not await group_quiz.on_answer(bot, answer):
        await quiz.on_answer(bot, answer)


@router.callback_query(F.data == "quiz:stop")
async def stop(call: CallbackQuery):
    await call.answer()
    if not await quiz.stop(call.bot, call.from_user.id):
        await call.message.answer("Bu test allaqachon yakunlangan.")
