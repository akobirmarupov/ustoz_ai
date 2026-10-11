"""Admin: sinflar, fanlar va fanga test yuklash (javobsiz testlar yoki kitobcha)."""
import asyncio
import re
import time
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from data import config
from database.db import Session
from database.models import BankChunk, BankTest, BankUpload, Grade, Mock, Question, Subject
from database.requests import create_tests, enqueue, grade_subjects, grades, subject_tests, test_questions
from filters.filters import IsAdmin
from keyboards.inline.buttons import adm_grade_kb, adm_grades_kb, confirm_kb, parts_kb, time_kb
from services.extract import SUPPORTED, chunks, extract_text, split_book, split_numbered_questions
from services.parser import FORMAT_HELP, parse_tests
from states.states import AdminContent, AdminManual

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

OPTION_LINE = re.compile(r"(?m)^[ \t]*[A-Da-dАБВГабвг][ \t]*[).]")


def looks_like_tests(text: str, blocks: list[str]) -> bool:
    """Raqamlangan bloklar va A) B) variantlar bo'lsa — javobsiz testlar, aks holda kitobcha."""
    return len(blocks) >= 5 and len(OPTION_LINE.findall(text)) >= len(blocks)


# ---------------- Sinflar ----------------

@router.message(Command("sinflar"))
async def grades_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏫 <b>Sinflar</b> (masalan: 8-sinf, DTM test kitobi)", reply_markup=adm_grades_kb(await grades()))


@router.callback_query(F.data == "cg:list")
async def grades_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("🏫 <b>Sinflar</b>", reply_markup=adm_grades_kb(await grades()))


@router.callback_query(F.data == "cg:add")
async def grade_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminContent.grade_name)
    await call.answer()
    await call.message.answer("✍️ Sinf nomini yozing (masalan: <b>8-sinf</b> yoki <b>DTM test kitobi</b>):")


@router.message(AdminContent.grade_name, F.text)
async def grade_save(message: Message, state: FSMContext):
    name = message.text.strip()[:64]
    try:
        async with Session() as s:
            s.add(Grade(name=name))
            await s.commit()
    except IntegrityError:
        await message.answer("Bunday sinf allaqachon bor. Boshqa nom yozing:")
        return
    await state.clear()
    await message.answer(f"✅ «{escape(name)}» qo'shildi.", reply_markup=adm_grades_kb(await grades()))


async def _grade_view(grade_id: int) -> tuple[str, object]:
    async with Session() as s:
        grade = await s.get(Grade, grade_id)
    items = await grade_subjects(grade_id)
    text = f"🏫 <b>{escape(grade.name)}</b>\n\nFanlar (qavs ichida savollar soni):" if items else \
        f"🏫 <b>{escape(grade.name)}</b>\n\nHali fan qo'shilmagan."
    return text, adm_grade_kb(grade_id, items)


@router.callback_query(F.data.regexp(r"^cg:\d+$"))
async def grade_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = await _grade_view(int(call.data.split(":")[1]))
    await call.answer()
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cg:del:"))
async def grade_del(call: CallbackQuery):
    gid = call.data.split(":")[2]
    await call.answer()
    await call.message.edit_text("⚠️ Sinf, uning barcha fanlari va savollari o'chiriladi. Ishonchingiz komilmi?",
                                 reply_markup=confirm_kb(f"cg:delok:{gid}", f"cg:{gid}"))


@router.callback_query(F.data.startswith("cg:delok:"))
async def grade_del_ok(call: CallbackQuery):
    gid = int(call.data.split(":")[2])
    async with Session() as s:
        subject_ids = (await s.execute(select(Subject.id).where(Subject.grade_id == gid))).scalars().all()
        await s.execute(delete(Question).where(Question.subject_id.in_(subject_ids)))
        await s.execute(delete(BankTest).where(BankTest.subject_id.in_(subject_ids)))
        await s.execute(delete(Subject).where(Subject.grade_id == gid))
        await s.execute(delete(Mock).where(Mock.grade_id == gid))
        await s.execute(delete(Grade).where(Grade.id == gid))
        await s.commit()
    await call.answer("O'chirildi")
    await call.message.edit_text("🏫 <b>Sinflar</b>", reply_markup=adm_grades_kb(await grades()))


# ---------------- Fanlar ----------------

@router.callback_query(F.data.startswith("cs:add:"))
async def subject_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminContent.subject_name)
    await state.update_data(grade_id=int(call.data.split(":")[2]))
    await call.answer()
    await call.message.answer("✍️ Fan nomini yozing (masalan: <b>Matematika</b>):")


@router.message(AdminContent.subject_name, F.text)
async def subject_save(message: Message, state: FSMContext):
    grade_id = (await state.get_data())["grade_id"]
    name = message.text.strip()[:64]
    try:
        async with Session() as s:
            s.add(Subject(grade_id=grade_id, name=name))
            await s.commit()
    except IntegrityError:
        await message.answer("Bu sinfda bunday fan bor. Boshqa nom yozing:")
        return
    await state.clear()
    text, kb = await _grade_view(grade_id)
    await message.answer(f"✅ «{escape(name)}» qo'shildi.\n\n{text}", reply_markup=kb)


@router.callback_query(F.data.regexp(r"^cs:\d+$"))
async def subject_open(call: CallbackQuery, state: FSMContext):
    await state.clear()
    sid = int(call.data.split(":")[1])
    await call.answer()
    text, kb = await _subject_view(sid)
    await call.message.edit_text(text, reply_markup=kb)


async def _subject_view(sid: int) -> tuple[str, InlineKeyboardMarkup]:
    async with Session() as s:
        subj = await s.get(Subject, sid)
        grade = await s.get(Grade, subj.grade_id)
        busy = (await s.execute(select(BankUpload).where(
            BankUpload.subject_id == sid, BankUpload.status == "processing"))).scalars().all()
    tests = await subject_tests(sid, only_filled=False)
    rows = [[InlineKeyboardButton(text=f"📝 {t.name} ({n})", callback_data=f"ct:{t.id}")] for t, n in tests]
    rows.append([InlineKeyboardButton(text="➕ Test qo'shish", callback_data=f"cu:{sid}")])
    rows.append([InlineKeyboardButton(text="🗑 Fanni o'chirish", callback_data=f"cs:del:{sid}"),
                 InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"cg:{subj.grade_id}")])
    extra = f"\n⏳ Tayyorlanayotgan fayllar: {len(busy)}" if busy else ""
    text = (f"🏫 {escape(grade.name)} → 📘 <b>{escape(subj.name)}</b>\n\n"
            f"Testlar: <b>{len(tests)}</b> ta (qavs ichida savollar soni){extra}")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("cs:del:"))
async def subject_del(call: CallbackQuery):
    sid = call.data.split(":")[2]
    await call.answer()
    await call.message.edit_text("⚠️ Fan, uning barcha testlari va savollari o'chiriladi. Ishonchingiz komilmi?",
                                 reply_markup=confirm_kb(f"cs:delok:{sid}", f"cs:{sid}"))


@router.callback_query(F.data.startswith("cs:delok:"))
async def subject_del_ok(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    async with Session() as s:
        subj = await s.get(Subject, sid)
        await s.execute(delete(Question).where(Question.subject_id == sid))
        await s.execute(delete(BankTest).where(BankTest.subject_id == sid))
        await s.execute(delete(Subject).where(Subject.id == sid))
        await s.commit()
    await call.answer("O'chirildi")
    text, kb = await _grade_view(subj.grade_id)
    await call.message.edit_text(text, reply_markup=kb)


# ---------------- Nomli testlar ----------------

@router.callback_query(F.data.regexp(r"^ct:\d+$"))
async def test_open(call: CallbackQuery):
    tid = int(call.data.split(":")[1])
    async with Session() as s:
        t = await s.get(BankTest, tid)
    if not t:
        await call.answer("Topilmadi", show_alert=True)
        return
    n = len(await test_questions(tid))
    await call.answer()
    await call.message.edit_text(
        f"📝 <b>{escape(t.name)}</b>\n\nSavollar: <b>{n}</b> ta\nHar bir savolga: ⏱ {t.time_limit} soniya",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Testni o'chirish", callback_data=f"ct:del:{tid}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"cs:{t.subject_id}")]]))


@router.callback_query(F.data.startswith("ct:del:"))
async def test_del(call: CallbackQuery):
    tid = call.data.split(":")[2]
    await call.answer()
    await call.message.edit_text("⚠️ Test va uning savollari o'chiriladi. Ishonchingiz komilmi?",
                                 reply_markup=confirm_kb(f"ct:delok:{tid}", f"ct:{tid}"))


@router.callback_query(F.data.startswith("ct:delok:"))
async def test_del_ok(call: CallbackQuery):
    tid = int(call.data.split(":")[2])
    async with Session() as s:
        t = await s.get(BankTest, tid)
        await s.execute(delete(Question).where(Question.test_id == tid))
        await s.execute(delete(BankTest).where(BankTest.id == tid))
        await s.commit()
    await call.answer("O'chirildi")
    text, kb = await _subject_view(t.subject_id)
    await call.message.edit_text(text, reply_markup=kb)


# ---------------- Test qo'shish: nom → usul → vaqt → hajm → fayl ----------------

MODE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🤖 AI orqali (javobsiz test yoki kitobcha)", callback_data="cm:ai")],
    [InlineKeyboardButton(text="📄 Avtomatik (javoblari bor tayyor test)", callback_data="cm:auto")],
    [InlineKeyboardButton(text="✍️ Qo'lda yozish", callback_data="cm:manual")],
])


def _size_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{n} ta", callback_data=f"csize:{n}") for n in config.ABI_TEST_SIZES]])


@router.callback_query(F.data.startswith("cu:"))
async def upload_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(subject_id=int(call.data.split(":")[1]))
    await state.set_state(AdminContent.test_name)
    await call.answer()
    await call.message.answer("✍️ Test nomini yozing.\nMasalan: <b>DTM test 1</b> yoki <b>Qisqa ko'paytirish formulalari</b>")


@router.message(AdminContent.test_name, F.text)
async def test_name(message: Message, state: FSMContext):
    name = message.text.strip()[:100]
    if len(name) < 2:
        await message.answer("Nom juda qisqa. Qaytadan yozing:")
        return
    await state.update_data(name=name)
    await state.set_state(None)
    await message.answer(f"📝 <b>{escape(name)}</b>\n\nTest qanday yaratilsin?", reply_markup=MODE_KB)


@router.callback_query(F.data.startswith("cm:"))
async def upload_mode(call: CallbackQuery, state: FSMContext):
    if "name" not in await state.get_data():
        await call.answer("Avval test nomini kiriting: ➕ Test qo'shish", show_alert=True)
        return
    await state.update_data(mode=call.data.split(":")[1])
    await state.set_state(AdminContent.time)
    await call.answer()
    await call.message.edit_text("⏱ Har bir savolga qancha vaqt berilsin?", reply_markup=time_kb("ctime"))


@router.callback_query(AdminContent.time, F.data.startswith("ctime:"))
async def upload_time(call: CallbackQuery, state: FSMContext):
    await state.update_data(time=int(call.data.split(":")[1]))
    data = await state.get_data()
    await call.answer()
    if data["mode"] == "manual":
        test_id = (await create_tests(data["subject_id"], data["name"], data["time"], 1))[0]
        await state.update_data(test_id=test_id)
        await state.set_state(AdminManual.question)
        await call.message.edit_text(
            f"✍️ <b>{escape(data['name'])}</b> — qo'lda yozish (har savolga {data['time']} soniya, "
            f"ko'pi bilan {config.MAX_TEST_QUESTIONS} ta savol)\n\n"
            "1-savol matnini yuboring.\n\n"
            "💡 Tezroq usul: bir xabarda bir nechta savolni javobi bilan yuborsangiz ham bo'ladi:\n"
            "<code>1. 2 + 2 = ?\nA) 3\n*B) 4\nC) 5</code>")
        return
    await call.message.edit_text(f"Bitta testda nechta savol bo'lsin? (ko'pi bilan {config.MAX_TEST_QUESTIONS})\n"
                                 "Faylda ko'proq savol bo'lsa, bir nechta testga bo'linadi: "
                                 f"«{escape(data['name'])} 1», «{escape(data['name'])} 2» ...",
                                 reply_markup=_size_kb())


@router.callback_query(AdminContent.time, F.data.startswith("csize:"))
async def upload_size(call: CallbackQuery, state: FSMContext):
    await state.update_data(size=int(call.data.split(":")[1]))
    data = await state.get_data()
    await state.set_state(AdminContent.upload)
    await call.answer()
    if data["mode"] == "auto":
        await call.message.edit_text("📤 Javoblari belgilangan test faylini yuboring (PDF, .docx, .txt).\n\n" + FORMAT_HELP)
    else:
        await call.message.edit_text("📤 PDF, Word (.docx) yoki .txt faylni yuboring.\n"
                                     "Javobsiz testlar yoki kitobcha — bot o'zi aniqlaydi.")


def _split_note(name: str, total: int, size: int) -> str:
    n = -(-total // size)
    return f"«{escape(name)}» nomli 1 ta test" if n == 1 else f"{n} ta test: «{escape(name)} 1» … «{escape(name)} {n}»"


@router.message(AdminContent.upload, F.document)
async def upload_file(message: Message, state: FSMContext):
    doc = message.document
    ext = Path(doc.file_name or "").suffix.lower()
    if ext not in SUPPORTED:
        await message.answer("Faqat PDF, .docx yoki .txt fayl. Eski .doc ni .docx qilib saqlang.")
        return
    if (doc.file_size or 0) > config.MAX_FILE_MB * 1024 * 1024:
        await message.answer(f"Fayl {config.MAX_FILE_MB} MB dan katta.")
        return
    path = config.UPLOADS_DIR / f"bank_{int(time.time())}{ext}"
    await message.bot.download(doc, destination=path)
    wait = await message.answer("⏳ Fayl o'qilmoqda...")
    text = await asyncio.to_thread(extract_text, path)
    if len(text.strip()) < 100:
        await wait.edit_text("⚠️ Fayldan matn topilmadi (skanerlangan PDF bo'lishi mumkin). Matnli PDF yoki Word yuboring.")
        return
    await state.update_data(file_path=str(path), file_name=doc.file_name[:250])
    data = await state.get_data()
    if data["mode"] == "auto":
        questions, skipped = parse_tests(text)
        if not questions:
            await wait.edit_text("⚠️ Javoblari belgilangan testlar topilmadi.\n\n" + FORMAT_HELP)
            return
        note = f"\n⚠️ {skipped} ta savolda javob aniqlanmadi — ular qo'shilmaydi." if skipped else ""
        await wait.edit_text(f"🔎 <b>{len(questions)}</b> ta javobli savol o'qildi.{note}\n"
                             f"Natija: {_split_note(data['name'], len(questions), data['size'])}.\n\n"
                             f"1-savol: <i>{escape(questions[0]['question'][:200])}</i>\n"
                             f"To'g'ri javob: <b>{escape(questions[0]['options'][questions[0]['answer']][:100])}</b>\n\n"
                             "Qo'shaymi?", reply_markup=confirm_kb("cauto:ok", "cauto:no"))
        return
    blocks = split_numbered_questions(text)
    if looks_like_tests(text, blocks):
        await wait.edit_text(f"🔎 Bu <b>javobsiz testlar</b> fayliga o'xshaydi: <b>{len(blocks)}</b> ta savol topildi.\n"
                             f"Natija: {_split_note(data['name'], len(blocks), data['size'])}.\n"
                             "AI javoblarini topib qo'shaymi?",
                             reply_markup=confirm_kb("cmode:tests", "cmode:book"))
    else:
        await wait.edit_text("🔎 Bu <b>kitobcha</b> (darslik matni) ga o'xshaydi.\nKitobchadan test tuzaymi?",
                             reply_markup=confirm_kb("cmode:book", "cmode:tests"))


@router.callback_query(AdminContent.upload, F.data == "cmode:tests")
async def mode_tests(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    text = await asyncio.to_thread(extract_text, data["file_path"])
    blocks = split_numbered_questions(text)
    if len(blocks) < 5:
        await call.message.edit_text("⚠️ Fayldan raqamlangan testlar topilmadi (1. 2. 3. ...). Kitobcha sifatida yuklang.")
        return
    groups = chunks(blocks, data["size"])
    test_ids = await create_tests(data["subject_id"], data["name"], data["time"], len(groups))
    await _create_upload(data, call.from_user.id, "tests", None, ["\n\n".join(g) for g in groups], test_ids)
    await call.message.edit_text(f"⏳ {len(blocks)} ta savolga AI javob topmoqda → "
                                 f"{_split_note(data['name'], len(blocks), data['size'])}. Tugagach xabar beraman.")


@router.callback_query(AdminContent.upload, F.data == "cmode:book")
async def mode_book(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminContent.book_parts)
    data = await state.get_data()
    await call.answer()
    await call.message.edit_text(f"📚 Kitobchadan nechta test tuzilsin? (har birida {data['size']} ta savol)",
                                 reply_markup=parts_kb("cparts"))


@router.callback_query(AdminContent.book_parts, F.data.startswith("cparts:"))
async def book_parts(call: CallbackQuery, state: FSMContext):
    parts = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    await call.answer()
    text = await asyncio.to_thread(extract_text, data["file_path"])
    sources = split_book(text, parts)
    test_ids = await create_tests(data["subject_id"], data["name"], data["time"], len(sources))
    await _create_upload(data, call.from_user.id, "book", data["size"], sources, test_ids)
    await call.message.edit_text(f"⏳ AI {len(sources)} × {data['size']} ta savol tuzmoqda → "
                                 f"{_split_note(data['name'], len(sources) * data['size'], data['size'])}. "
                                 "Tugagach xabar beraman.")


async def _create_upload(data: dict, admin_id: int, mode: str, per: int | None, sources: list[str],
                         test_ids: list[int]) -> int:
    async with Session() as s:
        up = BankUpload(subject_id=data["subject_id"], admin_id=admin_id, file_path=data["file_path"],
                        file_name=data["file_name"], mode=mode, per_part=per, time_limit=data.get("time", 30))
        s.add(up)
        await s.flush()
        items = [BankChunk(upload_id=up.id, test_id=tid, source_text=src) for src, tid in zip(sources, test_ids)]
        s.add_all(items)
        await s.commit()
        ids = [c.id for c in items]
    for cid in ids:
        await enqueue("bank_chunk", cid)
    return up.id


@router.callback_query(AdminContent.upload, F.data.startswith("cauto:"))
async def auto_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    if call.data.endswith("no"):
        await call.message.edit_text("❌ Bekor qilindi.")
        return
    text = await asyncio.to_thread(extract_text, data["file_path"])
    questions, _ = parse_tests(text)
    groups = chunks(questions, data["size"])
    test_ids = await create_tests(data["subject_id"], data["name"], data["time"], len(groups))
    async with Session() as s:
        up = BankUpload(subject_id=data["subject_id"], admin_id=call.from_user.id, file_path=data["file_path"],
                        file_name=data["file_name"], mode="auto", time_limit=data["time"], status="done",
                        added=len(questions))
        s.add(up)
        await s.flush()
        for group, tid in zip(groups, test_ids):
            s.add_all(_to_question(q, data["subject_id"], data["time"], tid, up.id) for q in group)
        await s.commit()
    await call.message.edit_text(f"✅ {len(questions)} ta savol qo'shildi → "
                                 f"{_split_note(data['name'], len(questions), data['size'])}.")


def _to_question(q: dict, subject_id: int, time: int, test_id: int, upload_id: int | None = None) -> Question:
    return Question(subject_id=subject_id, test_id=test_id, upload_id=upload_id, text=q["question"],
                    options=q["options"], answer=q["answer"], confident=q.get("confident", True), time_limit=time)


# ---------------- Qo'lda yozish ----------------

DONE_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Tugatish", callback_data="cman:done")]])


async def _manual_saved(message: Message, state: FSMContext, added: int):
    data = await state.get_data()
    total = len(await test_questions(data["test_id"]))
    if total >= config.MAX_TEST_QUESTIONS:
        await state.clear()
        await message.answer(f"✅ Saqlandi. «{escape(data['name'])}» to'ldi: <b>{total}</b> ta savol "
                             f"(ko'pi bilan {config.MAX_TEST_QUESTIONS}). Yangi test uchun «➕ Test qo'shish».")
        return
    await state.set_state(AdminManual.question)
    await message.answer(f"✅ {added} ta savol saqlandi. «{escape(data['name'])}» da jami: <b>{total}</b> ta.\n\n"
                         "Keyingi savol matnini yuboring:", reply_markup=DONE_KB)


@router.message(AdminManual.question, F.text)
async def manual_question(message: Message, state: FSMContext):
    data = await state.get_data()
    parsed, _ = parse_tests(message.text)
    if parsed:  # bir xabarda javobi bilan bir nechta savol
        room = config.MAX_TEST_QUESTIONS - len(await test_questions(data["test_id"]))
        parsed = parsed[:room]
        async with Session() as s:
            s.add_all(_to_question(q, data["subject_id"], data["time"], data["test_id"]) for q in parsed)
            await s.commit()
        await _manual_saved(message, state, len(parsed))
        return
    await state.update_data(q_text=message.text.strip()[:1000])
    await state.set_state(AdminManual.options)
    await message.answer("Variantlarni yuboring — <b>har biri yangi qatorda</b> (2 dan 6 tagacha):\n"
                         "<code>3\n4\n5\n6</code>")


@router.message(AdminManual.options, F.text)
async def manual_options(message: Message, state: FSMContext):
    opts = [re.sub(r"^\s*[A-Fa-fА-Еа-е]\s*[).]\s*", "", ln).strip() for ln in message.text.split("\n")]
    opts = [o[:300] for o in opts if o]
    if not 2 <= len(opts) <= 6:
        await message.answer("2 tadan 6 tagacha variant kerak, har biri yangi qatorda. Qaytadan yuboring:")
        return
    await state.update_data(q_opts=opts)
    await state.set_state(AdminManual.answer)
    rows = [[InlineKeyboardButton(text=f"{'ABCDEF'[i]}) {o[:40]}", callback_data=f"cman:{i}")] for i, o in enumerate(opts)]
    await message.answer("✅ To'g'ri javobni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(AdminManual.answer, F.data.regexp(r"^cman:\d$"))
async def manual_answer(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    q = {"question": data["q_text"], "options": data["q_opts"], "answer": int(call.data.split(":")[1])}
    async with Session() as s:
        s.add(_to_question(q, data["subject_id"], data["time"], data["test_id"]))
        await s.commit()
    await call.answer("Saqlandi ✅")
    await call.message.edit_text(f"✅ To'g'ri javob: <b>{'ABCDEF'[q['answer']]}</b>")
    await _manual_saved(call.message, state, 1)


@router.callback_query(F.data == "cman:done")
async def manual_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    total = len(await test_questions(data["test_id"])) if data.get("test_id") else 0
    await call.message.edit_text(f"🏁 Tugatildi. «{escape(data.get('name', ''))}» da jami: <b>{total}</b> ta savol.")


@router.message(AdminContent.upload)
async def upload_wrong(message: Message):
    await message.answer("Faylni hujjat (document) sifatida yuboring.")
