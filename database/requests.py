import random
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from database.db import Session
from database.models import Job, Order, Payment, TestPart, TestSet, Usage, User


def effective_plan(user: User) -> str:
    """Muddati o'tgan tarif avtomatik 'free' hisoblanadi."""
    if user.plan != "free" and user.plan_until and user.plan_until > datetime.now():
        return user.plan
    return "free"


async def get_user(user_id: int) -> User | None:
    async with Session() as s:
        return await s.get(User, user_id)


async def create_user(user_id: int, full_name: str, username: str | None, phone: str) -> User:
    async with Session() as s:
        user = User(id=user_id, full_name=full_name, username=username, phone=phone)
        s.add(user)
        await s.commit()
        return user


async def use_quota(user_id: int, kind: str, limit: int, amount: int = 1) -> tuple[bool, int]:
    """Kunlik limitdan `amount` tasini ishlatadi. (ruxsat, ishlatilgan) qaytaradi."""
    today = date.today()
    async with Session() as s:
        row = (await s.execute(select(Usage).where(
            Usage.user_id == user_id, Usage.day == today, Usage.kind == kind))).scalar_one_or_none()
        used = row.count if row else 0
        if used + amount > limit:
            return False, used
        if row:
            row.count += amount
        else:
            s.add(Usage(user_id=user_id, day=today, kind=kind, count=amount))
        await s.commit()
        return True, used + amount


async def refund_quota(user_id: int, kind: str):
    """AI xatosida limitni qaytarish."""
    async with Session() as s:
        row = (await s.execute(select(Usage).where(
            Usage.user_id == user_id, Usage.day == date.today(), Usage.kind == kind))).scalar_one_or_none()
        if row and row.count > 0:
            row.count -= 1
            await s.commit()


async def enqueue(kind: str, ref_id: int):
    async with Session() as s:
        s.add(Job(kind=kind, ref_id=ref_id))
        await s.commit()


async def new_payment(user_id: int, purpose: str, amount: int,
                      order_id: int | None = None, plan: str | None = None, ref_id: int | None = None) -> Payment:
    async with Session() as s:
        while True:
            code = f"UE-{random.randint(10000, 99999)}"
            exists = (await s.execute(select(Payment.id).where(Payment.code == code))).first()
            if not exists:
                break
        p = Payment(user_id=user_id, purpose=purpose, amount=amount, order_id=order_id, plan=plan, code=code,
                    ref_id=ref_id)
        s.add(p)
        await s.commit()
        return p


async def open_payment_for_order(order_id: int) -> Payment | None:
    """Buyurtma uchun hali yakunlanmagan to'lov bo'lsa, o'shani qaytaradi (takroriy to'lov yaratmaslik uchun)."""
    async with Session() as s:
        return (await s.execute(select(Payment).where(
            Payment.order_id == order_id, Payment.status.in_(("waiting_receipt", "pending")))
            .order_by(Payment.id.desc()))).scalars().first()


async def user_test_sets(user_id: int) -> list[TestSet]:
    async with Session() as s:
        return list((await s.execute(select(TestSet).where(TestSet.user_id == user_id)
                                     .order_by(TestSet.id.desc()).limit(20))).scalars())


async def set_parts(set_id: int) -> list[TestPart]:
    async with Session() as s:
        return list((await s.execute(select(TestPart).where(TestPart.set_id == set_id)
                                     .order_by(TestPart.number))).scalars())


async def user_doc_orders(user_id: int) -> list[Order]:
    async with Session() as s:
        return list((await s.execute(select(Order).where(Order.user_id == user_id, Order.kind != "test")
                                     .order_by(Order.id.desc()).limit(15))).scalars())


async def user_payments(user_id: int) -> list[Payment]:
    async with Session() as s:
        return list((await s.execute(select(Payment).where(Payment.user_id == user_id)
                                     .order_by(Payment.id.desc()).limit(10))).scalars())


async def stats() -> dict:
    today = datetime.combine(date.today(), datetime.min.time())
    month = today.replace(day=1)
    async with Session() as s:
        users = (await s.execute(select(func.count(User.id)))).scalar_one()
        new_today = (await s.execute(select(func.count(User.id)).where(User.created_at >= today))).scalar_one()
        premium = (await s.execute(select(func.count(User.id)).where(
            User.plan != "free", User.plan_until > datetime.now()))).scalar_one()
        pending = (await s.execute(select(func.count(Payment.id)).where(Payment.status == "pending"))).scalar_one()
        real = (Payment.status == "approved") & (Payment.method != "balance")  # hisobdan xarid — ikki marta sanalmaydi
        revenue_today = (await s.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            real, Payment.decided_at >= today))).scalar_one()
        revenue_month = (await s.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            real, Payment.decided_at >= month))).scalar_one()
        queued = (await s.execute(select(func.count(Job.id)).where(Job.status.in_(("queued", "running"))))).scalar_one()
    return dict(users=users, new_today=new_today, premium=premium, pending=pending,
                revenue_today=revenue_today, revenue_month=revenue_month, queued=queued)


async def pending_payments() -> list[Payment]:
    async with Session() as s:
        return list((await s.execute(select(Payment).where(Payment.status == "pending")
                                     .order_by(Payment.id).limit(20))).scalars())


# ---------------- Abituriyent: sinflar, fanlar, savollar ----------------
from database.models import Attempt, BankTest, Grade, Question, Subject  # noqa: E402


async def grades() -> list[Grade]:
    async with Session() as s:
        return list((await s.execute(select(Grade).order_by(Grade.name))).scalars())


async def grade_subjects(grade_id: int) -> list[tuple[Subject, int]]:
    """Sinfdagi fanlar va har biridagi savollar soni."""
    async with Session() as s:
        rows = await s.execute(
            select(Subject, func.count(Question.id)).outerjoin(Question, Question.subject_id == Subject.id)
            .where(Subject.grade_id == grade_id).group_by(Subject.id).order_by(Subject.name))
        return [(subj, n) for subj, n in rows.all()]


async def subject_count(subject_id: int) -> int:
    async with Session() as s:
        return (await s.execute(select(func.count(Question.id)).where(Question.subject_id == subject_id))).scalar_one()


async def subject_tests(subject_id: int, only_filled: bool = True) -> list[tuple["BankTest", int]]:
    """Fandagi nomli testlar va har biridagi savollar soni (yaratilish tartibida)."""
    async with Session() as s:
        q = (select(BankTest, func.count(Question.id)).outerjoin(Question, Question.test_id == BankTest.id)
             .where(BankTest.subject_id == subject_id).group_by(BankTest.id).order_by(BankTest.id))
        rows = [(t, n) for t, n in (await s.execute(q)).all()]
    return [r for r in rows if r[1]] if only_filled else rows


async def test_questions(test_id: int) -> list[Question]:
    async with Session() as s:
        return list((await s.execute(select(Question).where(Question.test_id == test_id)
                                     .order_by(Question.id))).scalars())


async def create_tests(subject_id: int, name: str, time_limit: int, count: int) -> list[int]:
    """`count` ta nomli test yaratadi: bitta bo'lsa — «Nom», ko'p bo'lsa — «Nom 1», «Nom 2» ..."""
    async with Session() as s:
        tests = [BankTest(subject_id=subject_id, name=name if count == 1 else f"{name} {i + 1}", time_limit=time_limit)
                 for i in range(count)]
        s.add_all(tests)
        await s.commit()
        return [t.id for t in tests]


async def migrate_orphan_questions():
    """Nomli testlar paydo bo'lishidan oldin qo'shilgan savollarni «<Fan> testi» nomli testlarga o'tkazadi."""
    async with Session() as s:
        orphans = (await s.execute(select(Question).where(Question.test_id.is_(None))
                                   .order_by(Question.subject_id, Question.id))).scalars().all()
        by_subject: dict[int, list[Question]] = {}
        for q in orphans:
            by_subject.setdefault(q.subject_id, []).append(q)
        for subject_id, qs in by_subject.items():
            subj = await s.get(Subject, subject_id)
            groups = [qs[i:i + 40] for i in range(0, len(qs), 40)]
            for i, group in enumerate(groups):
                name = f"{subj.name} testi" + (f" {i + 1}" if len(groups) > 1 else "")
                t = BankTest(subject_id=subject_id, name=name, time_limit=group[0].time_limit or 30)
                s.add(t)
                await s.flush()
                for q in group:
                    q.test_id = t.id
        await s.commit()


async def user_attempts(user_id: int, limit: int = 10) -> list[tuple[Attempt, str, str]]:
    """(urinish, test nomi yoki fan nomi, sinf nomi)."""
    async with Session() as s:
        rows = await s.execute(
            select(Attempt, func.coalesce(BankTest.name, Subject.name), Grade.name)
            .join(Subject, Subject.id == Attempt.subject_id).join(Grade, Grade.id == Subject.grade_id)
            .outerjoin(BankTest, BankTest.id == Attempt.test_id).where(Attempt.user_id == user_id)
            .order_by(Attempt.id.desc()).limit(limit))
        return [tuple(r) for r in rows.all()]


async def rating(since: datetime | None, exclude: list[int]) -> list[tuple[int, str, int, int]]:
    """Reyting: (user_id, ism, to'g'ri javoblar, jami savollar) — to'g'ri javoblar, keyin aniqlik bo'yicha."""
    async with Session() as s:
        q = (select(Attempt.user_id, User.full_name, func.sum(Attempt.score), func.sum(Attempt.total))
             .join(User, User.id == Attempt.user_id).group_by(Attempt.user_id, User.full_name))
        if since:
            q = q.where(Attempt.created_at >= since)
        if exclude:
            q = q.where(Attempt.user_id.not_in(exclude))
        rows = [(uid, name, int(score or 0), int(total or 0)) for uid, name, score, total in (await s.execute(q)).all()]
    rows.sort(key=lambda r: (-r[2], -(r[2] / r[3] if r[3] else 0), r[3]))
    return rows


# ---------------- Xatolar daftari ----------------
from database.models import Mistake, Mock, MockAttempt  # noqa: E402


async def record_result(user_id: int, question_id: int | None, ok: bool, review: bool = False):
    """Xato — daftarga qo'shiladi; daftardan ishlashda to'g'ri javob — daftardan o'chadi."""
    if not question_id:
        return
    async with Session() as s:
        row = (await s.execute(select(Mistake).where(
            Mistake.user_id == user_id, Mistake.question_id == question_id))).scalar_one_or_none()
        if not ok and not row:
            s.add(Mistake(user_id=user_id, question_id=question_id))
        elif ok and row and review:
            await s.delete(row)
        await s.commit()


async def mistakes_summary(user_id: int) -> list[tuple[int, str, str, int]]:
    """(fan id, fan nomi, sinf nomi, xatolar soni)."""
    async with Session() as s:
        rows = await s.execute(
            select(Subject.id, Subject.name, Grade.name, func.count(Mistake.id))
            .join(Question, Question.id == Mistake.question_id).join(Subject, Subject.id == Question.subject_id)
            .join(Grade, Grade.id == Subject.grade_id).where(Mistake.user_id == user_id)
            .group_by(Subject.id, Subject.name, Grade.name).order_by(Grade.name, Subject.name))
        return [tuple(r) for r in rows.all()]


async def mistake_questions(user_id: int, subject_id: int, limit: int) -> list[Question]:
    async with Session() as s:
        return list((await s.execute(
            select(Question).join(Mistake, Mistake.question_id == Question.id)
            .where(Mistake.user_id == user_id, Question.subject_id == subject_id)
            .order_by(Mistake.id).limit(limit))).scalars())


# ---------------- Mock ----------------

async def grade_mocks(grade_id: int | None = None) -> list[Mock]:
    async with Session() as s:
        q = select(Mock).order_by(Mock.id)
        if grade_id:
            q = q.where(Mock.grade_id == grade_id)
        return list((await s.execute(q)).scalars())


async def random_questions(subject_id: int, count: int) -> list[Question]:
    async with Session() as s:
        ids = (await s.execute(select(Question.id).where(Question.subject_id == subject_id))).scalars().all()
        pick = random.sample(list(ids), min(count, len(ids)))
        rows = (await s.execute(select(Question).where(Question.id.in_(pick)))).scalars().all()
    by_id = {q.id: q for q in rows}
    return [by_id[i] for i in pick if i in by_id]


async def mocks_taken(user_id: int, days: int) -> int:
    async with Session() as s:
        return (await s.execute(select(func.count(MockAttempt.id)).where(
            MockAttempt.user_id == user_id, MockAttempt.created_at >= datetime.now() - timedelta(days=days)))).scalar_one()


async def mock_rating(exclude: list[int]) -> list[tuple[int, str, float, float]]:
    """Har bir foydalanuvchining eng yaxshi mock natijasi (foiz bo'yicha): (user_id, ism, ball, max)."""
    async with Session() as s:
        q = select(MockAttempt.user_id, User.full_name, MockAttempt.ball, MockAttempt.max_ball).join(
            User, User.id == MockAttempt.user_id)
        if exclude:
            q = q.where(MockAttempt.user_id.not_in(exclude))
        best: dict[int, tuple] = {}
        for uid, name, ball, mx in (await s.execute(q)).all():
            pct = ball / mx if mx else 0
            if uid not in best or pct > best[uid][0]:
                best[uid] = (pct, name, ball, mx)
    return [(uid, v[1], v[2], v[3]) for uid, v in sorted(best.items(), key=lambda kv: -kv[1][0])]


async def today_usage(user_id: int, kind: str) -> int:
    async with Session() as s:
        row = (await s.execute(select(Usage.count).where(
            Usage.user_id == user_id, Usage.day == date.today(), Usage.kind == kind))).scalar_one_or_none()
        return row or 0


async def all_user_ids() -> list[int]:
    async with Session() as s:
        return list((await s.execute(select(User.id).where(User.is_blocked.is_(False)))).scalars())


# ---------------- Hisob (balans) ----------------
from database.models import BalanceTx  # noqa: E402


async def add_balance(user_id: int, amount: int, kind: str, note: str = "") -> int:
    """Hisobga pul qo'shadi (yoki manfiy bo'lsa ayiradi), yangi balansni qaytaradi."""
    async with Session() as s:
        user = (await s.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
        user.balance += amount
        s.add(BalanceTx(user_id=user_id, amount=amount, kind=kind, note=note[:255]))
        await s.commit()
        return user.balance


async def spend_balance(user_id: int, amount: int, note: str) -> bool:
    """Balans yetarli bo'lsa yechadi. Bir vaqtda ikki marta bosilsa ham ikki marta yechilmaydi."""
    async with Session() as s:
        user = (await s.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
        if user.balance < amount:
            return False
        user.balance -= amount
        s.add(BalanceTx(user_id=user_id, amount=-amount, kind="purchase", note=note[:255]))
        await s.commit()
        return True


async def balance_history(user_id: int, limit: int = 10) -> list[BalanceTx]:
    async with Session() as s:
        return list((await s.execute(select(BalanceTx).where(BalanceTx.user_id == user_id)
                                     .order_by(BalanceTx.id.desc()).limit(limit))).scalars())


async def referral_stats(user_id: int) -> tuple[int, int]:
    """(taklif qilingan do'stlar soni, ulardan topilgan bonus)."""
    async with Session() as s:
        count = (await s.execute(select(func.count(User.id)).where(User.referred_by == user_id))).scalar_one()
        earned = (await s.execute(select(func.coalesce(func.sum(BalanceTx.amount), 0)).where(
            BalanceTx.user_id == user_id, BalanceTx.kind == "referral"))).scalar_one()
        return count, earned


async def referral_bonuses_today(user_id: int) -> int:
    today = datetime.combine(date.today(), datetime.min.time())
    async with Session() as s:
        return (await s.execute(select(func.count(BalanceTx.id)).where(
            BalanceTx.user_id == user_id, BalanceTx.kind == "referral", BalanceTx.created_at >= today))).scalar_one()
