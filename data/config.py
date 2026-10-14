import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x]

# PostgreSQL: postgresql+asyncpg://user:parol@localhost:5432/ustoz_elite
# Sinash uchun SQLite ham ishlaydi (standart qiymat)
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+aiosqlite:///{BASE_DIR / 'ustoz_elite.db'}"

# Claude API (ANTHROPIC_API_KEY .env faylidan avtomatik olinadi)
AI_MODEL = os.getenv("AI_MODEL") or "claude-opus-5-5"

# To'lov ma'lumotlari (hozircha admin orqali qo'lda tasdiqlanadi)
CARD_NUMBER = os.getenv("CARD_NUMBER") or "0000 0000 0000 0000"
CARD_OWNER = os.getenv("CARD_OWNER", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

# Bir vaqtda nechta og'ir ish (fayl tayyorlash) bajarilsin
WORKERS = int(os.getenv("WORKERS") or 2)

MEDIA_DIR = BASE_DIR / "media"
UPLOADS_DIR = MEDIA_DIR / "uploads"
RESULTS_DIR = MEDIA_DIR / "results"
MAX_FILE_MB = 20  # Telegram bot API yuklab olish chegarasi

# ---------- Narxlar (so'm) ----------
PRICES = {
    "slide": 10_000,
    "referat": 10_000,
    "mustaqil": 10_000,
    "maqola": 35_000,
    "kurs": 35_000,
    "test": 40_000,         # AI orqali test tayyorlash
    "test_auto": 30_000,    # avtomatik (AI'siz, javobli fayldan)
    "test_manual": 30_000,  # qo'lda yozilgan test
}
QUESTION_TIMES = (10, 15, 20, 30)  # har bir savolga soniya (quiz taymeri)

# ---------- Hisob (balans) va bonuslar ----------
REF_BONUS = 1_500            # taklif qilingan har bir yangi do'st uchun
REF_DAILY_LIMIT = 20         # bir kunda ko'pi bilan nechta do'st uchun bonus
CHANNEL_BONUS = 2_000        # kanalga obuna uchun (bir marta)
CHANNEL = os.getenv("CHANNEL") or "@marupov_akobir"
TOPUP_AMOUNTS = (10_000, 20_000, 50_000, 100_000)
MIN_TOPUP, MAX_TOPUP = 5_000, 2_000_000
FREE_DOC_KINDS = ("slide", "referat", "mustaqil")  # 2 tasi bepul (turi farqi yo'q)
FREE_DOCS = 2

QUESTIONS_PER_PART = 30          # eski to'plamlar uchun (savollar soni tanlanmagan bo'lsa)
MAX_BOOK_PARTS = 20              # kitobchadan 1..20 qism
TEST_PART_SIZES = (20, 30, 40, 50)  # student: har bir testdagi savollar soni (fayl shu sondan bo'linadi)
ADMIN_BOOK_SIZES = (20, 30, 40)  # admin kitobchadan test tuzganda

# ---------- Abituriyent tariflari ----------
PLAN_DAYS = 30
# tests — kuniga ishlash mumkin bo'lgan nomli testlar (None = cheksiz), ai_chat — AI ustozga savollar
# mock — (nechta, necha kunda): (1, 30) = oyiga 1 ta; None = cheksiz
PLANS = {
    "free": {"name": "Bepul", "price": 0, "tests": 3, "ai_chat": 3, "mock": (1, 30)},
    "basic": {"name": "Basic", "price": 20_000, "tests": 5, "ai_chat": 15, "mock": (1, 7)},
    "pro": {"name": "Pro", "price": 30_000, "tests": 9, "ai_chat": 40, "mock": (3, 7)},
    "max": {"name": "Max Pro", "price": 40_000, "tests": None, "ai_chat": None, "mock": None},
}
MOCK_MINUTES = (60, 90, 120, 180)
MOCK_BLOCK_COUNTS = (10, 20, 30)
MOCK_POINTS = (1.1, 2.1, 3.1)
MISTAKES_PER_ROUND = 20
# «Cheksiz» AI uchun ko'rinmas himoya: bitta odam skript bilan AI xarajatini oshirib yubormasligi uchun
AI_FAIR_USE = 300
ABI_TEST_SIZES = (20, 30, 40)    # bitta nomli testdagi savollar soni (admin tanlaydi)
MAX_TEST_QUESTIONS = 40
