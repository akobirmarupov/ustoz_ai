"""Guruhda test o'tkazish: botni havola orqali guruhga qo'shish, boshlash, to'xtatish."""
from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from database.db import Session
from database.models import TestPart, TestSet
from services import group_quiz as gq

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

HOW_TO = ("ℹ️ Guruhda test o'tkazish uchun botga shaxsiy chatda kiring: /testlar → testni tanlang → "
          "«👥 Guruhda o'tkazish».")


async def _open_lobby(target: Message, part_id: int, owner_id: int):
    if (old := gq.get(target.chat.id)) and not old.finished:
        await target.answer("⏳ Bu guruhda test allaqachon ketmoqda. Avval uni yakunlang.")
        return
    async with Session() as s:
        part = await s.get(TestPart, part_id)
        ts = await s.get(TestSet, part.set_id) if part else None
    if not part or part.status != "ready" or not part.questions:
        await target.answer("⚠️ Bu test topilmadi yoki hali tayyor emas.")
        return
    session = gq.GroupQuiz(chat_id=target.chat.id, owner_id=owner_id, part_id=part.id,
                           title=ts.part_title(part.number), questions=part.questions,
                           time_limit=ts.time_limit or 30)
    text, kb = gq.lobby(session)
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
        await call.answer("Bu guruhda test allaqachon ketmoqda.", show_alert=True)
        return
    await call.answer()
    await _open_lobby(call.message, int(call.data.split(":")[2]), call.from_user.id)


@router.callback_query(F.data.in_({"gq:go", "gq:cancel", "gq:stop"}))
async def control(call: CallbackQuery):
    s = gq.get(call.message.chat.id)
    action = call.data.split(":")[1]
    if not s or s.finished or (action != "stop" and s.started):
        await call.answer("Bu tugma eskirgan.", show_alert=True)
        return
    if not await gq.can_control(call.bot, s, call.from_user.id):
        await call.answer("Faqat testni qo'shgan odam yoki guruh admini boshqara oladi.", show_alert=True)
        return
    await call.answer()
    if action == "go":
        await call.message.edit_reply_markup(reply_markup=None)
        await gq.start(call.bot, s)
    elif action == "cancel":
        gq.cancel(s)
        await call.message.edit_text("❌ Test bekor qilindi.")
    else:
        await gq.finish(call.bot, s, note="⏹ Test to'xtatildi.")
