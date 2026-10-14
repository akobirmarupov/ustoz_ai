"""Guruhda test o'tkazish: botni havola orqali guruhga qo'shish, boshlash, to'xtatish."""
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from database.db import Session
from database.models import TestPart, TestSet
from services import group_quiz as gq

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

HOW_TO = "ℹ️ " + gq.tr(
    "Guruhda test o'tkazish: bot bilan shaxsiy chatda /testlar → testni tanlang → «👥 Guruhda o'tkazish».",
    "Чтобы провести тест в группе: в личном чате с ботом /testlar → выберите тест → «👥 Guruhda o'tkazish».",
    "To run a quiz in a group: in a private chat with the bot, /testlar → pick a quiz → «👥 Guruhda o'tkazish».")


async def _open_lobby(target: Message, part_id: int, owner_id: int):
    if (old := gq.get(target.chat.id)) and not old.finished:
        await target.answer("⏳ " + gq.RUNNING)
        return
    async with Session() as s:
        part = await s.get(TestPart, part_id)
        ts = await s.get(TestSet, part.set_id) if part else None
    if not part or part.status != "ready" or not part.questions:
        await target.answer("⚠️ " + gq.SHORT.join(("Test topilmadi yoki hali tayyor emas", "Тест не найден или ещё не готов",
                                                  "Quiz not found or not ready yet")))
        return
    session = gq.GroupQuiz(chat_id=target.chat.id, owner_id=owner_id, part_id=part.id,
                           title=ts.part_title(part.number), questions=part.questions,
                           time_limit=ts.time_limit or 30)
    text, kb = await gq.lobby(target.bot, session)
    await target.answer(text, reply_markup=kb)


@router.message(CommandStart())
async def group_start(message: Message, command: CommandObject):
    part_id = gq.parse_payload(command.args)
    if part_id is None:
        await message.answer(HOW_TO)
        return
    await _open_lobby(message, part_id, message.from_user.id)


@router.callback_query(F.data.startswith("gq:again:"))
async def again(call: CallbackQuery):
    if (old := gq.get(call.message.chat.id)) and not old.finished:
        await call.answer(gq.RUNNING, show_alert=True)
        return
    await call.answer()
    await _open_lobby(call.message, int(call.data.split(":")[2]), call.from_user.id)


@router.callback_query(F.data.in_({"gq:go", "gq:cancel"}))
async def control(call: CallbackQuery):
    s = gq.get(call.message.chat.id)
    if not s or s.finished or s.started:
        await call.answer(gq.EXPIRED, show_alert=True)
        return
    if call.data == "gq:go":  # Start'ni guruhdagi istalgan odam bosa oladi; 3 kishi yig'ilganda boshlanadi
        go = gq.press_start(s, call.from_user.id, call.from_user.full_name)
        if go is None:
            await call.answer(gq.ALREADY, show_alert=True)
            return
        await call.answer("✅")
        if go:
            await gq.keep_on_top(call.bot, s, call.message)
            await gq.start(call.bot, s)
            return
        text, kb = await gq.lobby(call.bot, s)
        try:
            await call.message.edit_text(text, reply_markup=kb)
        except TelegramAPIError:
            pass
        return
    if not await gq.can_control(call.bot, s, call.from_user.id):
        await call.answer(gq.ONLY_OWNER, show_alert=True)
        return
    await call.answer()
    gq.cancel(s)
    await call.message.edit_text("❌ " + gq.SHORT.join(("Test bekor qilindi", "Тест отменён", "Quiz cancelled")))
