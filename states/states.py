from aiogram.fsm.state import State, StatesGroup


class Register(StatesGroup):
    name = State()
    phone = State()


class DocOrder(StatesGroup):
    topic = State()
    lang = State()
    size = State()
    titul = State()
    outline = State()


class TestOrder(StatesGroup):
    name = State()
    size = State()
    time = State()
    file = State()
    parts = State()
    per_part = State()


class Receipt(StatesGroup):
    wait = State()


class Tutor(StatesGroup):
    chat = State()


class AdminReject(StatesGroup):
    reason = State()


class AdminContent(StatesGroup):
    grade_name = State()
    subject_name = State()
    test_name = State()
    time = State()
    upload = State()
    book_parts = State()
    book_per = State()


class AdminManual(StatesGroup):
    question = State()
    options = State()
    answer = State()


class StudentManual(StatesGroup):
    question = State()
    options = State()
    answer = State()


class AdminMock(StatesGroup):
    name = State()
    building = State()


class Broadcast(StatesGroup):
    message = State()
    confirm = State()


class Topup(StatesGroup):
    amount = State()
