from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    full_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    plan: Mapped[str] = mapped_column(String(16), default="free")
    plan_until: Mapped[datetime | None] = mapped_column(DateTime)
    plan_reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    free_docs_used: Mapped[int] = mapped_column(Integer, default=0)
    free_test_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    balance: Mapped[int] = mapped_column(Integer, default=0)            # so'm, faqat bot ichida ishlatiladi
    referred_by: Mapped[int | None] = mapped_column(BigInteger)         # kim taklif qilgan
    channel_bonus: Mapped[bool] = mapped_column(Boolean, default=False)  # kanal bonusi olinganmi
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BalanceTx(Base):
    """Hisob tarixi: + to'ldirish/bonus, − xarid."""
    __tablename__ = "balance_tx"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # topup | referral | channel | purchase | admin
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Order(Base):
    """Student buyurtmasi: slayd, referat, mustaqil ish, maqola, kurs ishi yoki test."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    price: Mapped[int] = mapped_column(Integer, default=0)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result_path: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Payment(Base):
    """Chek orqali to'lov. Keyin Payme/Click ulanganda method va provider_txn_id ishlatiladi."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))           # order | premium
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    plan: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="waiting_receipt")  # waiting_receipt|pending|approved|rejected
    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    receipt_unique_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    receipt_type: Mapped[str | None] = mapped_column(String(16))  # photo | document
    reject_reason: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16), default="manual")
    provider_txn_id: Mapped[str | None] = mapped_column(String(128))
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class TestSet(Base):
    __tablename__ = "test_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(8))              # tests | book | auto (AI'siz)
    file_path: Mapped[str] = mapped_column(String(512))
    file_name: Mapped[str] = mapped_column(String(255))
    parts_count: Mapped[int] = mapped_column(Integer, default=0)
    per_part: Mapped[int | None] = mapped_column(Integer)       # kitobcha uchun: 20/30/35
    unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    time_limit: Mapped[int] = mapped_column(Integer, default=30)  # har bir savolga soniya


class TestPart(Base):
    __tablename__ = "test_parts"
    __table_args__ = (UniqueConstraint("set_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("test_sets.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="waiting")  # waiting|queued|ready|failed
    source_text: Mapped[str] = mapped_column(Text, default="")
    questions: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    """Fonda bajariladigan og'ir ishlar navbati (bot qotib qolmasligi uchun)."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))        # doc | test_prepare | test_part
    ref_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Usage(Base):
    """Kunlik limitlar hisobi."""
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "day", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(24))
    count: Mapped[int] = mapped_column(Integer, default=0)


# ---------------- Abituriyent: sinflar, fanlar, savollar bazasi ----------------

class Grade(Base):
    """Sinf yoki to'plam: «8-sinf», «DTM test kitobi» va hokazo."""
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("grade_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))


class BankTest(Base):
    """Fan ichidagi nomli test: «DTM test 1», «Qisqa ko'paytirish formulalari» (40 tagacha savol)."""
    __tablename__ = "bank_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    time_limit: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[int | None] = mapped_column(Integer, index=True)
    upload_id: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    answer: Mapped[int] = mapped_column(Integer)
    confident: Mapped[bool] = mapped_column(Boolean, default=True)
    time_limit: Mapped[int] = mapped_column(Integer, default=30)  # har bir savolga soniya
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BankUpload(Base):
    """Admin yuklagan fayl: javobsiz testlar yoki kitobcha."""
    __tablename__ = "bank_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    admin_id: Mapped[int] = mapped_column(BigInteger)
    file_path: Mapped[str] = mapped_column(String(512))
    file_name: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(8))          # tests | book | auto | manual
    per_part: Mapped[int | None] = mapped_column(Integer)
    time_limit: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(16), default="processing")
    added: Mapped[int] = mapped_column(Integer, default=0)


class BankChunk(Base):
    """Yuklangan faylning bo'lagi (har biri alohida fon ishi)."""
    __tablename__ = "bank_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("bank_uploads.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | done | failed


class Attempt(Base):
    """Abituriyent ishlagan test natijasi."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    test_id: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Mock(Base):
    """Mock imtihon shabloni: bir nechta fan bloki, umumiy vaqt va ballar."""
    __tablename__ = "mocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    minutes: Mapped[int] = mapped_column(Integer, default=180)
    blocks: Mapped[list] = mapped_column(JSON, default=list)  # [{"subject_id", "count", "points"}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MockAttempt(Base):
    __tablename__ = "mock_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    mock_id: Mapped[int] = mapped_column(Integer, index=True)
    ball: Mapped[float] = mapped_column(Float, default=0)
    max_ball: Mapped[float] = mapped_column(Float, default=0)
    details: Mapped[list] = mapped_column(JSON, default=list)  # [{"subject", "correct", "count", "ball"}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Mistake(Base):
    """Xatolar daftari: foydalanuvchi xato javob bergan savollar."""
    __tablename__ = "mistakes"
    __table_args__ = (UniqueConstraint("user_id", "question_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
