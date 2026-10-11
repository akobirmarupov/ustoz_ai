"""Admin: mock imtihon yaratish (fan bloklari, savollar soni, ball, umumiy vaqt)."""
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup, Message
from sqlalchemy import delete

from data import config
from database.db import Session
from database.models import Grade, Mock, Subject
from database.requests import grade_mocks, grade_subjects
from filters.filters import IsAdmin
from handlers.users.mock import fmt_ball, mock_info
from states.states import AdminMock

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _list(grade_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with Session() as s:
        grade = await s.get(Grade, grade_id)
    mocks = await grade_mocks(grade_id)
    rows = [[B(text=f"🧪 {m.name}", callback_data=f"cmk:o:{m.id}")] for m in mocks]
    rows.append([B(text="➕ Mock qo'shish", callback_data=f"cmk:add:{grade_id}")])
    rows.append([B(text="⬅️ Orqaga", callback_data=f"cg:{grade_id}")])
    return f"🏫 {escape(grade.name)} → 🧪 <b>Mock imtihonlar</b>: {len(mocks)} ta", InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.regexp(r"^cmk:\d+$"))
async def mocks(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _list(int(call.data.split(":")[1]))
    await call.answer()
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cmk:o:"))
async def mock_open(call: CallbackQuery):
    async with Session() as s:
        mock = await s.get(Mock, int(call.data.split(":")[2]))
    blocks, total, mx = await mock_info(mock)
    await call.answer()
    await call.message.edit_text(
        f"🧪 <b>{escape(mock.name)}</b>\n\n{blocks}\n\nJami: {total} ta savol · ⏳ {mock.minutes} daqiqa · "
        f"maksimal {fmt_ball(mx)} ball",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [B(text="🗑 O'chirish", callback_data=f"cmk:del:{mock.id}")],
            [B(text="⬅️ Orqaga", callback_data=f"cmk:{mock.grade_id}")]]))


@router.callback_query(F.data.startswith("cmk:del:"))
async def mock_del(call: CallbackQuery):
    async with Session() as s:
        mock = await s.get(Mock, int(call.data.split(":")[2]))
        gid = mock.grade_id
        await s.execute(delete(Mock).where(Mock.id == mock.id))
        await s.commit()
    await call.answer("O'chirildi")
    text, kb = await _list(gid)
    await call.message.edit_text(text, reply_markup=kb)


# ---------------- Yaratish: nom → vaqt → bloklar ----------------

@router.callback_query(F.data.startswith("cmk:add:"))
async def add(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(grade_id=int(call.data.split(":")[2]), blocks=[])
    await state.set_state(AdminMock.name)
    await call.answer()
    await call.message.answer("✍️ Mock nomini yozing.\nMasalan: <b>DTM: Matematika + Fizika</b>")


@router.message(AdminMock.name, F.text)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(AdminMock.building)
    rows = [[B(text=f"⏳ {m} daqiqa", callback_data=f"cmkm:{m}") for m in config.MOCK_MINUTES]]
    await message.answer("Umumiy vaqt qancha?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _ask_subject(message: Message, state: FSMContext, edit: bool = True):
    data = await state.get_data()
    items = await grade_subjects(data["grade_id"])
    rows = [[B(text=f"📘 {s.name} ({n} savol)", callback_data=f"cmkb:{s.id}")] for s, n in items if n]
    if not rows:
        await message.answer("⚠️ Bu sinf fanlarida hali savollar yo'q. Avval testlar qo'shing.")
        await state.clear()
        return
    text = f"{_summary(data)}\n\n{len(data['blocks']) + 1}-blok: qaysi fan?"
    await (message.edit_text if edit else message.answer)(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def _summary(data: dict) -> str:
    lines = [f"🧪 <b>{escape(data['name'])}</b> · ⏳ {data.get('minutes', '?')} daqiqa"]
    for i, b in enumerate(data["blocks"], 1):
        lines.append(f"{i}. {escape(b['name'])}: {b['count']} ta × {fmt_ball(b['points'])} ball")
    return "\n".join(lines)


@router.callback_query(AdminMock.building, F.data.startswith("cmkm:"))
async def add_minutes(call: CallbackQuery, state: FSMContext):
    await state.update_data(minutes=int(call.data.split(":")[1]))
    await call.answer()
    await _ask_subject(call.message, state)


@router.callback_query(AdminMock.building, F.data.startswith("cmkb:"))
async def add_block_subject(call: CallbackQuery, state: FSMContext):
    sid = int(call.data.split(":")[1])
    async with Session() as s:
        subj = await s.get(Subject, sid)
    await state.update_data(cur={"subject_id": sid, "name": subj.name})
    await call.answer()
    rows = [[B(text=f"{n} ta savol", callback_data=f"cmkc:{n}") for n in config.MOCK_BLOCK_COUNTS]]
    await call.message.edit_text(f"📘 {escape(subj.name)}: nechta savol?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminMock.building, F.data.startswith("cmkc:"))
async def add_block_count(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(cur=data["cur"] | {"count": int(call.data.split(":")[1])})
    await call.answer()
    rows = [[B(text=f"{fmt_ball(p)} ball", callback_data=f"cmkp:{p}") for p in config.MOCK_POINTS]]
    await call.message.edit_text("Har bir to'g'ri javobga necha ball?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminMock.building, F.data.startswith("cmkp:"))
async def add_block_points(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    blocks = data["blocks"] + [data["cur"] | {"points": float(call.data.split(":")[1])}]
    await state.update_data(blocks=blocks, cur=None)
    data = await state.get_data()
    await call.answer()
    await call.message.edit_text(_summary(data), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [B(text="➕ Yana blok qo'shish", callback_data="cmkmore")],
        [B(text="✅ Saqlash", callback_data="cmksave"), B(text="❌ Bekor", callback_data=f"cmk:{data['grade_id']}")]]))


@router.callback_query(AdminMock.building, F.data == "cmkmore")
async def more(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await _ask_subject(call.message, state)


@router.callback_query(AdminMock.building, F.data == "cmksave")
async def save(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    blocks = [{"subject_id": b["subject_id"], "count": b["count"], "points": b["points"]} for b in data["blocks"]]
    async with Session() as s:
        s.add(Mock(grade_id=data["grade_id"], name=data["name"], minutes=data["minutes"], blocks=blocks))
        await s.commit()
    await call.answer("Saqlandi ✅")
    text, kb = await _list(data["grade_id"])
    await call.message.edit_text(f"✅ Mock saqlandi.\n\n{text}", reply_markup=kb)
