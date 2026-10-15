"""Ustoz uchun guruh Mock'i: yaratish (bazadan va/yoki o'z faylidan), 50 000 so'm to'lov, guruh havolasi, natijalar.

Savollar Mock yaratilganda bir marta tanlanadi — qaysi guruhda o'tkazilmasin, hammaga bir xil savollar tushadi.
Guruhda o'tkazish va reyting: services/group_quiz.py (kind="mock").
"""
import asyncio
import time
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select

from data import config
from database.db import Session
from database.models import Grade, GroupMock, GroupMockResult, Payment, Subject
from database.requests import grade_subjects, grades, random_questions
from filters.filters import Registered
from keyboards.default.menu import abituriyent_menu, cancel_menu
from services import group_quiz as gq
from services.extract import SUPPORTED, extract_text
from services.parser import FORMAT_HELP, parse_tests
from services.payments import money, start_payment
from states.states import GroupMockBuild

router = Router()
router.message.filter(Registered())
router.callback_query.filter(Registered())

POINTS = (1.0,) + tuple(config.MOCK_POINTS)
B = InlineKeyboardButton


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def entry_rows() -> list[list[InlineKeyboardButton]]:
    """«🧪 Mock imtihon» ro'yxati ostidagi ustoz tugmalari."""
    return [[B(text=f"👨‍🏫 Guruh uchun Mock yaratish ({money(config.GROUP_MOCK_PRICE)})", callback_data="gm:new")],
            [B(text="📂 Mening Mock'larim", callback_data="gm:my")]]


# ---------------- Yaratish ----------------

@router.callback_query(F.data == "gm:new")
async def new_mock(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await state.set_state(GroupMockBuild.title)
    await call.message.answer(
        "👨‍🏫 <b>Guruh uchun Mock</b>\n\n"
        "Mock'ni o'zingiz tuzasiz: bazadagi tayyor testlardan (fan → sinf → savollar soni) va/yoki o'z test "
        "faylingizdan. Keyin botni guruhga qo'shasiz — a'zolar birga ishlaydi, oxirida reyting chiqadi.\n\n"
        f"💰 Narxi: <b>{money(config.GROUP_MOCK_PRICE)}</b> (bitta Mock uchun, istalgancha guruhda o'tkazish mumkin)\n\n"
        "✍️ Mock nomini yozing (masalan: <b>DTM sinov — 1-mavsum</b>):", reply_markup=cancel_menu())


@router.message(GroupMockBuild.title, F.text)
async def mock_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not 2 <= len(title) <= 100:
        await message.answer("Nom 2–100 belgi bo'lsin. Qayta yozing:")
        return
    await state.update_data(title=title, blocks=[], questions=[], time=30)
    await state.set_state(GroupMockBuild.building)
    await message.answer("✅ Nom saqlandi.", reply_markup=abituriyent_menu())
    await _show_builder(message, state)


def _summary(data: dict) -> str:
    qs = data["questions"]
    lines = [f"• {escape(b['title'])}: {b['count']} ta × {gq.fmt_ball(b['points'])} ball" for b in data["blocks"]]
    body = "\n".join(lines) if lines else "<i>Hali savol qo'shilmadi</i>"
    mx = sum(q["points"] for q in qs)
    return (f"🧪 <b>{escape(data['title'])}</b>\n\n{body}\n\n"
            f"Jami: <b>{len(qs)}</b>/{config.GROUP_MOCK_MAX_Q} ta savol · maksimal <b>{gq.fmt_ball(mx)}</b> ball · "
            f"⏱ har savolga <b>{data['time']}</b> s")


async def _show_builder(message: Message, state: FSMContext, edit: bool = False):
    data = await state.get_data()
    rows = [[B(text="📚 Bazadan qo'shish", callback_data="gmb:bank"),
             B(text="📎 Fayldan qo'shish", callback_data="gmb:file")],
            [B(text=f"⏱ Vaqt: {data['time']} s (o'zgartirish)", callback_data="gmb:time")]]
    if data["questions"]:
        rows.append([B(text=f"✅ Tayyor — {money(config.GROUP_MOCK_PRICE)}", callback_data="gmb:done")])
    rows.append([B(text="❌ Bekor qilish", callback_data="gmb:cancel")])
    text = _summary(data) + "\n\nSavollarni qo'shing 👇"
    if edit:
        await message.edit_text(text, reply_markup=_kb(rows))
    else:
        await message.answer(text, reply_markup=_kb(rows))


async def _building(call: CallbackQuery, state: FSMContext) -> dict | None:
    """Mock tuzish holatida ekanini tekshiradi (eski tugma bosilsa — ogohlantiradi)."""
    data = await state.get_data()
    if "questions" not in data:
        await call.answer("Bu oyna eskirgan. «🧪 Mock imtihon» → «👨‍🏫 Guruh uchun Mock yaratish»", show_alert=True)
        return None
    return data


@router.callback_query(F.data == "gmb:cancel")
async def build_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ Mock yaratish bekor qilindi.")


@router.callback_query(F.data == "gmb:back")
async def build_back(call: CallbackQuery, state: FSMContext):
    if await _building(call, state) is None:
        return
    await call.answer()
    await state.set_state(GroupMockBuild.building)
    await _show_builder(call.message, state, edit=True)


@router.callback_query(F.data == "gmb:time")
async def build_time(call: CallbackQuery, state: FSMContext):
    data = await _building(call, state)
    if data is None:
        return
    times = config.QUESTION_TIMES
    nxt = times[(times.index(data["time"]) + 1) % len(times)] if data["time"] in times else times[-1]
    await state.update_data(time=nxt)
    await call.answer(f"⏱ {nxt} s")
    await _show_builder(call.message, state, edit=True)


def _points_kb(prefix: str) -> InlineKeyboardMarkup:
    return _kb([[B(text=f"{gq.fmt_ball(p)} ball", callback_data=f"{prefix}:{i}") for i, p in enumerate(POINTS)],
                [B(text="⬅️ Orqaga", callback_data="gmb:back")]])


# --- bazadan ---

@router.callback_query(F.data == "gmb:bank")
async def bank_grades(call: CallbackQuery, state: FSMContext):
    if await _building(call, state) is None:
        return
    items = await grades()
    await call.answer()
    rows = [[B(text=f"📚 {g.name}", callback_data=f"gmb:g:{g.id}")] for g in items]
    await call.message.edit_text("📚 Fanni tanlang:", reply_markup=_kb(rows + [[B(text="⬅️ Orqaga", callback_data="gmb:back")]]))


@router.callback_query(F.data.startswith("gmb:g:"))
async def bank_subjects(call: CallbackQuery, state: FSMContext):
    if await _building(call, state) is None:
        return
    grade_id = int(call.data.split(":")[2])
    items = [(s, n) for s, n in await grade_subjects(grade_id) if n]
    async with Session() as s:
        grade = await s.get(Grade, grade_id)
    await call.answer()
    rows = [[B(text=f"🏫 {subj.name} · {n} ta savol", callback_data=f"gmb:s:{subj.id}")] for subj, n in items]
    await call.message.edit_text(f"📚 <b>{escape(grade.name)}</b>\n\n🏫 Sinf yoki bo'limni tanlang:",
                                 reply_markup=_kb(rows + [[B(text="⬅️ Orqaga", callback_data="gmb:bank")]]))


@router.callback_query(F.data.startswith("gmb:s:"))
async def bank_count(call: CallbackQuery, state: FSMContext):
    data = await _building(call, state)
    if data is None:
        return
    sid = int(call.data.split(":")[2])
    room = config.GROUP_MOCK_MAX_Q - len(data["questions"])
    if room <= 0:
        await call.answer(f"Mock'da ko'pi bilan {config.GROUP_MOCK_MAX_Q} ta savol bo'ladi.", show_alert=True)
        return
    counts = [c for c in config.GROUP_MOCK_COUNTS if c <= room] or [room]
    await call.answer()
    await call.message.edit_text("🔢 Bu bo'limdan nechta savol olinsin?", reply_markup=_kb(
        [[B(text=str(c), callback_data=f"gmb:c:{sid}:{c}") for c in counts],
         [B(text="⬅️ Orqaga", callback_data="gmb:bank")]]))


@router.callback_query(F.data.startswith("gmb:c:"))
async def bank_points(call: CallbackQuery, state: FSMContext):
    if await _building(call, state) is None:
        return
    _, _, sid, count = call.data.split(":")
    await call.answer()
    await call.message.edit_text("🎯 Har bir to'g'ri javob necha ball bo'lsin?", reply_markup=_points_kb(f"gmb:p:{sid}:{count}"))


@router.callback_query(F.data.startswith("gmb:p:"))
async def bank_add(call: CallbackQuery, state: FSMContext):
    data = await _building(call, state)
    if data is None:
        return
    _, _, sid, count, pi = call.data.split(":")
    sid, points = int(sid), POINTS[int(pi)]
    count = min(int(count), config.GROUP_MOCK_MAX_Q - len(data["questions"]))
    used = {q.get("id") for q in data["questions"]}
    rows = [q for q in await random_questions(sid, count + len(used)) if q.id not in used][:count]
    if not rows:
        await call.answer("Bu bo'limda yangi savol qolmadi.", show_alert=True)
        return
    async with Session() as s:
        subj = await s.get(Subject, sid)
        grade = await s.get(Grade, subj.grade_id)
    questions = data["questions"] + [{"id": q.id, "question": q.text, "options": q.options, "answer": q.answer,
                                      "points": points} for q in rows]
    blocks = data["blocks"] + [{"title": f"{grade.name} · {subj.name}", "count": len(rows), "points": points}]
    await state.update_data(questions=questions, blocks=blocks)
    await call.answer(f"✅ {len(rows)} ta savol qo'shildi")
    await _show_builder(call.message, state, edit=True)


# --- fayldan ---

@router.callback_query(F.data == "gmb:file")
async def file_ask(call: CallbackQuery, state: FSMContext):
    if await _building(call, state) is None:
        return
    await call.answer()
    await state.set_state(GroupMockBuild.file)
    await call.message.answer("📎 Test faylini yuboring (PDF, Word .docx yoki .txt).\n\n" + FORMAT_HELP,
                              reply_markup=_kb([[B(text="⬅️ Orqaga", callback_data="gmb:back")]]))


@router.message(GroupMockBuild.file, F.document)
async def file_got(message: Message, state: FSMContext):
    doc = message.document
    ext = Path(doc.file_name or "").suffix.lower()
    if ext not in SUPPORTED:
        await message.answer("Faqat PDF, Word (.docx) yoki .txt fayl qabul qilinadi.")
        return
    if (doc.file_size or 0) > config.MAX_FILE_MB * 1024 * 1024:
        await message.answer(f"Fayl {config.MAX_FILE_MB} MB dan katta. Kichikroq fayl yuboring.")
        return
    path = config.UPLOADS_DIR / f"gm_{message.from_user.id}_{int(time.time())}{ext}"
    await message.bot.download(doc, destination=path)
    try:
        text = await asyncio.to_thread(extract_text, path)
        parsed, skipped = parse_tests(text)
    except Exception:
        parsed, skipped = [], 0
    finally:
        path.unlink(missing_ok=True)
    if not parsed:
        await message.answer("⚠️ Fayldan javobi belgilangan savol topilmadi. Formatni tekshirib, qayta yuboring.\n\n"
                             + FORMAT_HELP)
        return
    data = await state.get_data()
    room = config.GROUP_MOCK_MAX_Q - len(data["questions"])
    if room <= 0:
        await message.answer(f"Mock'da ko'pi bilan {config.GROUP_MOCK_MAX_Q} ta savol bo'ladi.")
        return
    parsed = parsed[:room]
    await state.update_data(pending=parsed, pending_name=(doc.file_name or "Fayl")[:60])
    await state.set_state(GroupMockBuild.building)
    note = f" ({skipped} tasi o'qilmadi)" if skipped else ""
    await message.answer(f"✅ Fayldan <b>{len(parsed)}</b> ta savol olindi{note}.\n\n"
                         "🎯 Har bir to'g'ri javob necha ball bo'lsin?", reply_markup=_points_kb("gmb:fp"))


@router.message(GroupMockBuild.file)
async def file_wrong(message: Message):
    await message.answer("📎 Test faylini hujjat (document) sifatida yuboring.")


@router.callback_query(F.data.startswith("gmb:fp:"))
async def file_add(call: CallbackQuery, state: FSMContext):
    data = await _building(call, state)
    if data is None:
        return
    pending = data.get("pending") or []
    if not pending:
        await call.answer("Avval faylni yuboring.", show_alert=True)
        return
    points = POINTS[int(call.data.split(":")[2])]
    questions = data["questions"] + [{"question": q["question"], "options": q["options"], "answer": q["answer"],
                                      "points": points} for q in pending]
    blocks = data["blocks"] + [{"title": data.get("pending_name") or "Fayl", "count": len(pending), "points": points}]
    await state.update_data(questions=questions, blocks=blocks, pending=[], pending_name="")
    await call.answer(f"✅ {len(pending)} ta savol qo'shildi")
    await _show_builder(call.message, state, edit=True)


# --- yakunlash va to'lov ---

@router.callback_query(F.data == "gmb:done")
async def build_done(call: CallbackQuery, state: FSMContext, db_user):
    data = await _building(call, state)
    if data is None:
        return
    if not data["questions"]:
        await call.answer("Avval savol qo'shing.", show_alert=True)
        return
    is_admin = db_user.id in config.ADMINS
    async with Session() as s:
        mock = GroupMock(owner_id=db_user.id, title=data["title"], questions=data["questions"],
                         blocks=data["blocks"], time_limit=data["time"], paid=is_admin)
        s.add(mock)
        await s.commit()
    await state.clear()
    await call.answer()
    await call.message.edit_text(_summary(data) + "\n\n✅ Mock saqlandi.")
    if is_admin:
        await call.message.answer("👑 Admin uchun bepul. Botni guruhga qo'shing 👇",
                                  reply_markup=_kb([[B(text="👥 Guruhga qo'shish", url=await gq.mock_link(call.bot, mock.id))]]))
        return
    await start_payment(call.bot, db_user.id, "gmock", config.GROUP_MOCK_PRICE, f"🧪 Guruh Mock: {data['title']}",
                        ref_id=mock.id)


# ---------------- Mening Mock'larim ----------------

async def _owned(call: CallbackQuery, mock_id: int) -> GroupMock | None:
    async with Session() as s:
        mock = await s.get(GroupMock, mock_id)
    if not mock or mock.owner_id != call.from_user.id:
        await call.answer("Mock topilmadi.", show_alert=True)
        return None
    return mock


@router.callback_query(F.data == "gm:my")
async def my_mocks(call: CallbackQuery):
    async with Session() as s:
        mocks = (await s.execute(select(GroupMock).where(GroupMock.owner_id == call.from_user.id)
                                 .order_by(GroupMock.id.desc()).limit(30))).scalars().all()
    await call.answer()
    if not mocks:
        await call.message.answer("📂 Sizda hali Mock yo'q.", reply_markup=_kb(entry_rows()[:1]))
        return
    rows = [[B(text=f"{'✅' if m.paid else '💳'} {m.title} · {len(m.questions)} ta", callback_data=f"gm:o:{m.id}")]
            for m in mocks]
    await call.message.answer("📂 <b>Mening Mock'larim</b>\n✅ — to'langan, 💳 — to'lov kutilmoqda", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("gm:o:"))
async def mock_open(call: CallbackQuery):
    mock = await _owned(call, int(call.data.split(":")[2]))
    if not mock:
        return
    async with Session() as s:
        runs = (await s.execute(select(func.count(func.distinct(GroupMockResult.run_id)))
                                .where(GroupMockResult.mock_id == mock.id))).scalar_one()
    await call.answer()
    data = {"title": mock.title, "blocks": mock.blocks, "questions": mock.questions, "time": mock.time_limit}
    if mock.paid:
        text = _summary(data) + f"\n\n✅ To'langan · o'tkazilgan: <b>{runs}</b> marta"
        rows = [[B(text="👥 Guruhga qo'shish", url=await gq.mock_link(call.bot, mock.id))],
                [B(text="📊 Natijalar", callback_data=f"gm:r:{mock.id}")]]
    else:
        text = _summary(data) + f"\n\n💳 To'lov kutilmoqda: <b>{money(config.GROUP_MOCK_PRICE)}</b>"
        rows = [[B(text="💳 To'lash", callback_data=f"gm:pay:{mock.id}")],
                [B(text="🗑 O'chirish", callback_data=f"gm:del:{mock.id}")]]
    await call.message.answer(text, reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("gm:pay:"))
async def mock_pay(call: CallbackQuery):
    mock = await _owned(call, int(call.data.split(":")[2]))
    if not mock:
        return
    if mock.paid:
        await call.answer("Bu Mock allaqachon to'langan.", show_alert=True)
        return
    async with Session() as s:
        pending = (await s.execute(select(Payment.id).where(
            Payment.purpose == "gmock", Payment.ref_id == mock.id, Payment.status == "pending"))).first()
    if pending:
        await call.answer("⏳ To'lovingiz tekshirilmoqda. Tasdiqlangach xabar beraman.", show_alert=True)
        return
    await call.answer()
    await start_payment(call.bot, call.from_user.id, "gmock", config.GROUP_MOCK_PRICE, f"🧪 Guruh Mock: {mock.title}",
                        ref_id=mock.id)


@router.callback_query(F.data.startswith("gm:del:"))
async def mock_delete(call: CallbackQuery):
    mock = await _owned(call, int(call.data.split(":")[2]))
    if not mock:
        return
    if mock.paid:  # to'langan Mock natijalari bilan birga saqlanadi
        await call.answer("To'langan Mock'ni o'chirib bo'lmaydi.", show_alert=True)
        return
    async with Session() as s:
        await s.execute(delete(GroupMock).where(GroupMock.id == mock.id, GroupMock.paid.is_(False)))
        await s.commit()
    await call.answer("🗑 O'chirildi")
    await call.message.edit_text(f"🗑 «{escape(mock.title)}» o'chirildi.")


@router.callback_query(F.data.startswith("gm:r:"))
async def mock_results(call: CallbackQuery):
    """Oxirgi o'tkazishlar ro'yxati; bittasini tanlasa — to'liq reyting."""
    mock = await _owned(call, int(call.data.split(":")[2]))
    if not mock:
        return
    async with Session() as s:
        runs = (await s.execute(
            select(GroupMockResult.run_id, func.max(GroupMockResult.chat_title), func.min(GroupMockResult.created_at),
                   func.count(GroupMockResult.id))
            .where(GroupMockResult.mock_id == mock.id).group_by(GroupMockResult.run_id)
            .order_by(func.min(GroupMockResult.created_at).desc()).limit(10))).all()
    await call.answer()
    if not runs:
        await call.message.answer("📊 Bu Mock hali hech bir guruhda o'tkazilmagan.")
        return
    rows = [[B(text=f"👥 {title or 'Guruh'} · {at:%d.%m %H:%M} · {n} kishi", callback_data=f"gm:rr:{mock.id}:{run_id}")]
            for run_id, title, at, n in runs]
    await call.message.answer(f"📊 <b>{escape(mock.title)}</b> — o'tkazishlar:", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("gm:rr:"))
async def run_results(call: CallbackQuery):
    _, _, mock_id, run_id = call.data.split(":", 3)
    mock = await _owned(call, int(mock_id))
    if not mock:
        return
    async with Session() as s:
        res = (await s.execute(select(GroupMockResult).where(GroupMockResult.mock_id == mock.id,
                                                             GroupMockResult.run_id == run_id))).scalars().all()
    await call.answer()
    res = sorted(res, key=lambda r: (-r.ball, -r.correct, r.seconds))
    if not res:
        await call.message.answer("Natija topilmadi.")
        return
    head = (f"📊 <b>{escape(mock.title)}</b>\n👥 {escape(res[0].chat_title or 'Guruh')} · "
            f"{res[0].created_at:%d.%m.%Y %H:%M}\nQatnashchilar: <b>{len(res)}</b>\n")
    lines = [gq.rank_line(i, f"@{r.username}" if r.username else r.name, r.correct, r.total, r.seconds, r.ball)
             for i, r in enumerate(res)]
    for chunk in gq.split_text(head + "\n" + "\n".join(lines)):
        await call.message.answer(chunk)
