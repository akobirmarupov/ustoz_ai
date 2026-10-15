from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import config
from data.constants import DOC_KINDS, LANGS, SUBJECTS


def langs_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, name in LANGS.items():
        kb.button(text=name, callback_data=f"lang:{code}")
    return kb.adjust(3).as_markup()


def sizes_kb(kind: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, value in DOC_KINDS[kind]["sizes"]:
        kb.button(text=label, callback_data=f"size:{value}")
    return kb.adjust(3).as_markup()


def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[B(text="⏭ O'tkazib yuborish", callback_data="titul:skip")]])


def outline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="✅ Tasdiqlash", callback_data="outline:ok")],
        [B(text="🔄 Boshqa reja", callback_data="outline:again"), B(text="❌ Bekor", callback_data="outline:cancel")],
    ])


def paid_kb(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[B(text="✅ To'lov qildim", callback_data=f"paid:{payment_id}")]])


REJECT_REASONS = {
    "sum": "To'lov summasi to'liq emas",
    "notfound": "To'lov tushmagan",
    "bad": "Chek o'qilmaydi yoki noto'g'ri",
}


def admin_payment_kb(payment_id: int) -> InlineKeyboardMarkup:
    rows = [[B(text="✅ Tasdiqlash", callback_data=f"adm:ok:{payment_id}")]]
    rows += [[B(text=f"❌ {txt}", callback_data=f"adm:no:{payment_id}:{code}")] for code, txt in REJECT_REASONS.items()]
    rows.append([B(text="✍️ Boshqa sabab", callback_data=f"adm:no:{payment_id}:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_source_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🤖 AI: javobsiz testlarga javob topish", callback_data="tsrc:tests")],
        [B(text="🤖 AI: kitobchadan test tuzish", callback_data="tsrc:book")],
        [B(text="📄 Avtomatik: javoblari bor tayyor test", callback_data="tsrc:auto")],
        [B(text="✍️ Qo'lda yozish", callback_data="tsrc:manual")],
    ])


def time_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in config.QUESTION_TIMES:
        kb.button(text=f"⏱ {n} soniya", callback_data=f"{prefix}:{n}")
    return kb.adjust(2).as_markup()


def parts_kb(prefix: str = "bparts") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in range(1, config.MAX_BOOK_PARTS + 1):
        kb.button(text=str(n), callback_data=f"{prefix}:{n}")
    return kb.adjust(5).as_markup()


def part_size_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for n in config.TEST_PART_SIZES:
        kb.button(text=f"{n} ta savol", callback_data=f"tsize:{n}")
    return kb.adjust(4).as_markup()


PART_ICON = {"ready": "✅", "waiting": "🔒", "queued": "⏳", "failed": "⚠️"}


def set_menu_kb(ts, parts: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in parts:
        kb.button(text=f"{PART_ICON.get(p.status, '⏳')} {ts.part_title(p.number)}", callback_data=f"tpart:{p.id}")
    kb.adjust(2 if ts.name else 3)
    if not ts.unlocked and any(p.status == "waiting" for p in parts):
        kb.row(B(text="🔓 Ochish (to'lov)", callback_data=f"unlock:{ts.id}"))
    kb.row(B(text="🔄 Yangilash", callback_data=f"tset:{ts.id}"))
    return kb.as_markup()


def part_menu_kb(part_id: int, set_id: int, group_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="▶️ O'zim ishlayman", callback_data=f"tgo:{part_id}")],
        [B(text="👥 Guruhda o'tkazish", url=group_url)],
        [B(text="📋 Testlar ro'yxati", callback_data=f"tset:{set_id}")],
    ])


def after_test_kb(part_id: int, set_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🔁 Qayta ishlash", callback_data=f"tgo:{part_id}"),
         B(text="👥 Guruhda", callback_data=f"tpart:{part_id}")],
        [B(text="📋 Testlar ro'yxati", callback_data=f"tset:{set_id}")],
    ])


def subjects_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, name in SUBJECTS.items():
        kb.button(text=name, callback_data=f"subj:{code}")
    return kb.adjust(2).as_markup()


def plans_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code in ("basic", "pro", "max"):
        p = config.PLANS[code]
        star = " ⭐️" if code == "pro" else ""
        kb.button(text=f"{p['name']}{star} — {p['price']:,} so'm".replace(",", " "), callback_data=f"plan:{code}")
    return kb.adjust(1).as_markup()


# ---------------- Abituriyent: test ishlash ----------------

def grades_kb(items, prefix: str = "agr") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for g in items:
        kb.button(text=f"📚 {g.name}", callback_data=f"{prefix}:{g.id}")
    return kb.adjust(2).as_markup()


def abi_subjects_kb(items, grade_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for subj, n in items:
        if n:
            kb.button(text=f"🏫 {subj.name}", callback_data=f"asb:{subj.id}")
    kb.adjust(2)
    kb.row(B(text="⬅️ Fanlar", callback_data="abi:grades"))
    return kb.as_markup()


def ready_kb(subject_id: int, count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        B(text="✅ Ha, boshladik", callback_data=f"ago:{subject_id}:{count}"),
        B(text="❌ Yo'q", callback_data="abi:no"),
    ]])


# ---------------- Admin: sinflar, fanlar ----------------

def adm_grades_kb(items) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for g in items:
        kb.button(text=f"🏫 {g.name}", callback_data=f"cg:{g.id}")
    kb.adjust(2)
    kb.row(B(text="➕ Sinf qo'shish", callback_data="cg:add"))
    return kb.as_markup()


def adm_grade_kb(grade_id: int, items) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for subj, n in items:
        kb.button(text=f"📘 {subj.name} ({n})", callback_data=f"cs:{subj.id}")
    kb.adjust(2)
    kb.row(B(text="➕ Fan qo'shish", callback_data=f"cs:add:{grade_id}"))
    kb.row(B(text="🧪 Mock imtihonlar", callback_data=f"cmk:{grade_id}"))
    kb.row(B(text="🗑 Sinfni o'chirish", callback_data=f"cg:del:{grade_id}"),
           B(text="⬅️ Sinflar", callback_data="cg:list"))
    return kb.as_markup()


def confirm_kb(yes: str, no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[B(text="✅ Ha", callback_data=yes), B(text="❌ Yo'q", callback_data=no)]])
