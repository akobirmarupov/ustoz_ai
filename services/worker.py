"""Fon ishchisi: hujjat va testlarni navbat bilan tayyorlaydi, tarif muddatlarini kuzatadi."""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update

from data import config
from data.constants import KIND_TITLES
from database.db import Session
from database.models import BankChunk, BankUpload, Grade, Job, Order, Question, Subject, TestPart, TestSet, User
from database.requests import enqueue
from keyboards.inline.buttons import set_menu_kb
from services import ai
from services.documents import build_docx, build_essay, build_pptx
from services.extract import chunks, extract_text, split_book, split_numbered_questions, text_windows
from services.parser import parse_tests
from services.payments import start_payment

log = logging.getLogger(__name__)
_take_lock = asyncio.Lock()
MAX_ATTEMPTS = 2


class PermanentError(Exception):
    """Qayta urinish foyda bermaydigan xato (masalan, faylda matn yo'q)."""


async def _notify(bot: Bot, user_id: int, text: str, **kw):
    try:
        await bot.send_message(user_id, text, **kw)
    except TelegramAPIError as e:
        log.warning("Xabar yuborilmadi %s: %s", user_id, e)


async def _notify_admins(bot: Bot, text: str):
    for admin in config.ADMINS:
        await _notify(bot, admin, text)


def _safe_name(title: str) -> str:
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", name)[:60] or "fayl"


# ---------------- Hujjatlar ----------------

async def process_doc(bot: Bot, order_id: int):
    async with Session() as s:
        order = await s.get(Order, order_id)
        order.status = "processing"
        await s.commit()
    p = order.params
    titul = p.get("titul", [])
    if order.kind == "slide":
        data = await ai.make_slides(p["topic"], p["lang"], p["size"], p["outline"])
        path = config.RESULTS_DIR / f"{order.id}.pptx"
        await asyncio.to_thread(build_pptx, data, titul, p["lang"], path, order.id)
    elif order.kind == "esse":
        data = await ai.make_essay(p["topic"], p["lang"], p["size"], p["outline"], titul[0] if titul else "")
        path = config.RESULTS_DIR / f"{order.id}.docx"
        await asyncio.to_thread(build_essay, data, titul, p["lang"], path)
    else:
        data = await ai.make_document(order.kind, p["topic"], p["lang"], p["size"], p["outline"])
        path = config.RESULTS_DIR / f"{order.id}.docx"
        await asyncio.to_thread(build_docx, order.kind, data, titul, p["lang"], path)
    async with Session() as s:
        o = await s.get(Order, order_id)
        o.status, o.result_path = "done", str(path)
        await s.commit()
    await bot.send_document(
        order.user_id, FSInputFile(path, filename=f"{_safe_name(order.title)}{path.suffix}"),
        caption=f"✅ <b>{KIND_TITLES[order.kind]}</b> tayyor!\n📌 {order.title}\n\n"
                "Faylni ochib, kerak bo'lsa o'zingiz tahrirlashingiz mumkin.")


async def fail_doc(bot: Bot, order_id: int, err: Exception):
    async with Session() as s:
        order = await s.get(Order, order_id)
        order.status, order.error = "failed", str(err)
        if order.is_free:
            user = await s.get(User, order.user_id)
            user.free_docs_used = max(0, user.free_docs_used - 1)
        await s.commit()
    if order.is_free:
        await _notify(bot, order.user_id, "⚠️ Ishingizni tayyorlab bo'lmadi. Bepul urinishingiz qaytarildi, "
                                          "birozdan keyin qayta urinib ko'ring.")
    else:
        support = f" @{config.SUPPORT_USERNAME}" if config.SUPPORT_USERNAME else ""
        await _notify(bot, order.user_id, "⚠️ Ishingizni tayyorlashda xatolik bo'ldi. Admin bu haqda xabardor, "
                                          f"tez orada qayta tayyorlab beramiz.{support}")
        await _notify_admins(bot, f"⚠️ To'langan buyurtma #{order.id} bajarilmadi: {err}")


# ---------------- Testlar ----------------

async def process_test_prepare(bot: Bot, set_id: int):
    async with Session() as s:
        ts = await s.get(TestSet, set_id)
        order = await s.get(Order, ts.order_id)
    text = await asyncio.to_thread(extract_text, ts.file_path)
    if len(text.strip()) < 200:
        raise PermanentError("Fayldan matn topilmadi. Skanerlangan (rasm ko'rinishidagi) PDF bo'lishi mumkin — "
                             "matnli PDF yoki Word fayl yuboring.")

    ready_qs: list[list[dict]] | None = None  # avtomatik usulda savollar darhol tayyor
    size = ts.per_part or config.QUESTIONS_PER_PART  # 500 ta bo'lsa ham shu sondan bo'linadi, oxirgisi — qolgani
    if ts.source == "auto":
        questions, skipped = parse_tests(text)
        if not questions:
            raise PermanentError("Javoblari belgilangan testlar topilmadi. Har bir savolda to'g'ri javob "
                                 "belgilangan bo'lishi kerak (masalan *B) yoki «Javob: B» yoki oxirida javoblar kaliti).")
        ready_qs = chunks(questions, size)
        sources = [""] * len(ready_qs)
        info = (f"📄 Fayldan <b>{len(questions)}</b> ta javobli test o'qildi → <b>{len(sources)}</b> ta test "
                f"(har birida {size} tagacha).")
        if skipped:
            info += f"\n⚠️ {skipped} ta savolda javob aniqlanmadi va tashlab ketildi."
    elif ts.source == "tests":
        blocks = split_numbered_questions(text)
        if len(blocks) < 5:
            blocks = []
            for window in text_windows(text):
                blocks += await ai.split_raw_questions(window)
        if not blocks:
            raise PermanentError("Fayldan testlar topilmadi.")
        sources = ["\n\n".join(g) for g in chunks(blocks, size)]
        info = (f"📄 Fayldan <b>{len(blocks)}</b> ta test topildi → <b>{len(sources)}</b> ta test "
                f"(har birida {size} tagacha).")
    else:
        sources = split_book(text, ts.parts_count)
        info = f"📚 Kitobcha <b>{len(sources)}</b> qismga bo'lindi, har qismda <b>{ts.per_part}</b> ta savol bo'ladi."

    free = bool(order.params.get("free_first"))  # eski buyurtmalar: faqat test_1 bepul
    admin = ts.unlocked or bool(order.params.get("admin"))  # to'langan yoki bepul — hammasi ochiq
    open_now = "ready" if ready_qs else "queued"
    async with Session() as s:
        ts = await s.get(TestSet, set_id)
        ts.parts_count = len(sources)
        ts.unlocked = admin
        parts = [TestPart(set_id=set_id, number=i + 1, source_text=src,
                          questions=ready_qs[i] if ready_qs else None,
                          status=open_now if (admin or (free and i == 0)) else "waiting")
                 for i, src in enumerate(sources)]
        s.add_all(parts)
        o = await s.get(Order, order.id)
        o.status = "processing" if admin else "free_part" if free else "awaiting_payment"
        await s.commit()
        first_id = parts[0].id
        part_ids = [p.id for p in parts]

    if ready_qs and (admin or free):
        # AI kerak emas — ochiq qismlar shu zahoti tayyor
        await _notify(bot, order.user_id, info)
        if admin:
            await _finish_if_complete(bot, ts)
        else:
            await _announce_free_part(bot, ts)
    elif admin:
        for pid in part_ids:
            await enqueue("test_part", pid)
        await _notify(bot, order.user_id, info + "\n\n⏳ Barcha qismlar tayyorlanmoqda, tayyor bo'lgach xabar beraman.")
    elif free:
        await enqueue("test_part", first_id)
        await _notify(bot, order.user_id, info + f"\n\n🎁 <b>{escape(ts.part_title(1))}</b> bepul tayyorlanmoqda, "
                                                  "tayyor bo'lgach xabar beraman.")
    else:
        await _notify(bot, order.user_id, info)
        await start_payment(bot, order.user_id, "order", order.price, f"Test: {ts.title}", order_id=order.id)


async def fail_test_prepare(bot: Bot, set_id: int, err: Exception):
    msg = str(err) if isinstance(err, PermanentError) else "Faylni o'qishda xatolik bo'ldi, qayta urinib ko'ring."
    async with Session() as s:
        ts = await s.get(TestSet, set_id)
        order = await s.get(Order, ts.order_id)
        if ts.unlocked:  # to'langan/bepul buyurtma: pul kuymaydi, boshqa fayl yuborish mumkin
            order.status, order.error = "paid", str(err)
            await s.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text="📎 Boshqa fayl yuborish", callback_data=f"tstart:{order.id}")]])
            await _notify(bot, order.user_id, f"⚠️ {msg}", reply_markup=kb)
            return
        order.status, order.error = "failed", str(err)
        if order.params.get("free_first"):
            user = await s.get(User, order.user_id)
            user.free_test_used = False
        await s.commit()
    await _notify(bot, order.user_id, f"⚠️ {msg}")


async def _finish_if_complete(bot: Bot, ts: TestSet):
    async with Session() as s:
        parts = (await s.execute(select(TestPart).where(TestPart.set_id == ts.id).order_by(TestPart.number))).scalars().all()
        if any(p.status in ("queued", "waiting") for p in parts):
            return
        order = await s.get(Order, ts.order_id)
        order.status = "done"
        await s.commit()
    failed = [p.number for p in parts if p.status == "failed"]
    text = ("✅ <b>Barcha testlar tayyor!</b> Testni tanlab o'zingiz ishlang yoki guruhda o'tkazing 👇")
    if failed:
        text += "\n\n⚠️ Tayyorlanmagan qismlar: " + ", ".join(escape(ts.part_title(n)) for n in failed) + ". Admin xabardor."
        await _notify_admins(bot, f"⚠️ Test to'plami #{ts.id}: tayyorlanmagan qismlar {failed}")
    await _notify(bot, ts.user_id, text, reply_markup=set_menu_kb(ts, parts))


async def process_test_part(bot: Bot, part_id: int):
    async with Session() as s:
        part = await s.get(TestPart, part_id)
        ts = await s.get(TestSet, part.set_id)
    if ts.source == "tests":
        questions = await ai.answer_questions([part.source_text])
    else:
        questions = await ai.questions_from_text(part.source_text, ts.per_part)
    if not questions:
        raise PermanentError("Savollar tuzilmadi")
    async with Session() as s:
        p = await s.get(TestPart, part_id)
        p.questions, p.status = questions, "ready"
        await s.commit()

    if not ts.unlocked:  # bepul test_1
        await _announce_free_part(bot, ts)
    else:
        await _finish_if_complete(bot, ts)


async def _announce_free_part(bot: Bot, ts: TestSet):
    async with Session() as s:
        parts = (await s.execute(select(TestPart).where(TestPart.set_id == ts.id).order_by(TestPart.number))).scalars().all()
        order = await s.get(Order, ts.order_id)
        if len(parts) == 1:
            order.status = "done"
            await s.commit()
    rest = len(parts) - 1
    text = f"🎁 <b>{escape(ts.part_title(1))}</b> tayyor! Bosing va ishlang 👇"
    if rest:
        text += f"\n\nQolgan <b>{rest}</b> ta qismni ochish — <b>{order.price:,} so'm</b>.".replace(",", " ")
    await _notify(bot, ts.user_id, text, reply_markup=set_menu_kb(ts, parts))


async def fail_test_part(bot: Bot, part_id: int, err: Exception):
    async with Session() as s:
        part = await s.get(TestPart, part_id)
        part.status, part.error = "failed", str(err)
        ts = await s.get(TestSet, part.set_id)
        await s.commit()
    if ts.unlocked:
        await _finish_if_complete(bot, ts)
    else:
        await _notify(bot, ts.user_id, "⚠️ test_1 ni tayyorlab bo'lmadi. Admin xabardor, tez orada hal qilamiz.")
        await _notify_admins(bot, f"⚠️ Bepul test_1 (to'plam #{ts.id}) tayyorlanmadi: {err}")


# ---------------- Abituriyent savollar bazasi (admin yuklagan fayllar) ----------------

async def process_bank_chunk(bot: Bot, chunk_id: int):
    async with Session() as s:
        chunk = await s.get(BankChunk, chunk_id)
        up = await s.get(BankUpload, chunk.upload_id)
    if up.mode == "tests":
        questions = await ai.answer_questions([chunk.source_text])
    else:
        questions = await ai.questions_from_text(chunk.source_text, up.per_part)
    if not questions:
        raise PermanentError("Savollar tuzilmadi")
    async with Session() as s:
        s.add_all(Question(subject_id=up.subject_id, test_id=chunk.test_id, upload_id=up.id, text=q["question"],
                           options=q["options"], answer=q["answer"], confident=q["confident"],
                           time_limit=up.time_limit) for q in questions)
        c = await s.get(BankChunk, chunk_id)
        c.status = "done"
        u = await s.get(BankUpload, up.id)
        u.added += len(questions)
        await s.commit()
    await _finish_upload(bot, up.id)


async def fail_bank_chunk(bot: Bot, chunk_id: int, err: Exception):
    async with Session() as s:
        c = await s.get(BankChunk, chunk_id)
        c.status = "failed"
        await s.commit()
    await _finish_upload(bot, c.upload_id)


async def _finish_upload(bot: Bot, upload_id: int):
    async with Session() as s:
        up = await s.get(BankUpload, upload_id)
        states = (await s.execute(select(BankChunk.status).where(BankChunk.upload_id == upload_id))).scalars().all()
        if "queued" in states or up.status != "processing":
            return
        up.status = "done"
        subj = await s.get(Subject, up.subject_id)
        grade = await s.get(Grade, subj.grade_id)
        unsure = (await s.execute(select(Question.id).where(
            Question.upload_id == upload_id, Question.confident.is_(False)))).scalars().all()
        await s.commit()
    failed = states.count("failed")
    text = (f"✅ <b>{escape(up.file_name)}</b> tayyor!\n🏫 {escape(grade.name)} → 📘 {escape(subj.name)}\n"
            f"Bazaga qo'shildi: <b>{up.added}</b> ta savol.")
    if unsure:
        text += f"\n⚠️ {len(unsure)} ta savolda AI javobga to'liq ishonchsiz (testda ogohlantirish chiqadi)."
    if failed:
        text += f"\n⚠️ {failed} ta bo'lak tayyorlanmadi — faylni qayta yuklab ko'rishingiz mumkin."
    await _notify(bot, up.admin_id, text)


HANDLERS = {"doc": (process_doc, fail_doc),
            "test_prepare": (process_test_prepare, fail_test_prepare),
            "test_part": (process_test_part, fail_test_part),
            "bank_chunk": (process_bank_chunk, fail_bank_chunk)}


# ---------------- Navbat ----------------

async def _take_job() -> Job | None:
    async with _take_lock, Session() as s:
        job = (await s.execute(select(Job).where(Job.status == "queued").order_by(Job.id).limit(1))).scalar_one_or_none()
        if not job:
            return None
        job.status = "running"
        job.attempts += 1
        await s.commit()
        return job


async def _set_job(job_id: int, status: str, error: str | None = None):
    async with Session() as s:
        job = await s.get(Job, job_id)
        job.status, job.error = status, error
        await s.commit()


async def _loop(bot: Bot):
    while True:
        job = await _take_job()
        if not job:
            await asyncio.sleep(2)
            continue
        run, fail = HANDLERS[job.kind]
        try:
            await run(bot, job.ref_id)
            await _set_job(job.id, "done")
        except Exception as e:  # noqa: BLE001 — har qanday xato navbatni to'xtatmasligi kerak
            log.exception("Ish #%s (%s) xatosi", job.id, job.kind)
            if job.attempts < MAX_ATTEMPTS and not isinstance(e, PermanentError):
                await _set_job(job.id, "queued", str(e))
            else:
                await _set_job(job.id, "failed", str(e))
                await fail(bot, job.ref_id, e)


async def _periodic(bot: Bot):
    """Tarif tugashidan 3 kun oldin eslatma, tugaganda bepulga o'tkazish."""
    while True:
        now = datetime.now()
        async with Session() as s:
            soon = (await s.execute(select(User).where(
                User.plan != "free", User.plan_reminded.is_(False),
                User.plan_until > now, User.plan_until < now + timedelta(days=3)))).scalars().all()
            expired = (await s.execute(select(User).where(User.plan != "free", User.plan_until <= now))).scalars().all()
            for u in soon:
                u.plan_reminded = True
            for u in expired:
                u.plan, u.plan_reminded = "free", False
            await s.commit()
        for u in soon:
            await _notify(bot, u.id, f"⏰ ⭐️ Premium tarifingiz <b>{u.plan_until:%d.%m.%Y}</b> da tugaydi. "
                                     "Uzaytirish uchun Abituriyent → «⭐️ Premium».")
        for u in expired:
            await _notify(bot, u.id, "ℹ️ Premium muddati tugadi, hisobingiz Bepul tarifga o'tdi. "
                                     "Natijalaringiz saqlanib qoldi.")
        await asyncio.sleep(600)


async def run_worker(bot: Bot):
    # Bot qayta ishga tushganda yarim qolgan ishlarni navbatga qaytaramiz
    async with Session() as s:
        await s.execute(update(Job).where(Job.status == "running").values(status="queued"))
        await s.commit()
    tasks = [_loop(bot) for _ in range(config.WORKERS)] + [_periodic(bot)]
    await asyncio.gather(*tasks)
