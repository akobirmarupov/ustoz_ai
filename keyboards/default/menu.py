from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from data.constants import *  # noqa: F403


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
                               resize_keyboard=True)


def main_menu() -> ReplyKeyboardMarkup:
    return _kb([[BTN_ABITURIYENT, BTN_STUDENT], [BTN_BALANCE, BTN_INVITE], [BTN_PROFILE, BTN_PAYMENTS], [BTN_HELP]])


def abituriyent_menu() -> ReplyKeyboardMarkup:
    return _kb([[BTN_SOLVE, BTN_CREATE], [BTN_TUTOR, BTN_RESULTS], [BTN_MOCK, BTN_MISTAKES],
                [BTN_RATING, BTN_PREMIUM], [BTN_BACK]])


def student_menu() -> ReplyKeyboardMarkup:
    b = [v["button"] for v in DOC_KINDS.values()]
    return _kb([[b[0], b[1], b[2]], [b[3], b[4], BTN_TEST], [BTN_MY_WORKS, BTN_BACK]])


def cancel_menu() -> ReplyKeyboardMarkup:
    return _kb([[BTN_CANCEL]])


def phone_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)
