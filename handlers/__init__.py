from aiogram import Router

from handlers.admin import admin, broadcast, content, mocks
from handlers.users import (abi_tests, abituriyent, balance, common, fallback, mistakes, mock, payments, quiz, rating,
                            start, student, tests)


def setup_handlers() -> Router:
    main_router = Router()
    # Tartib muhim: «Bekor qilish» va admin buyruqlari har qanday holatda birinchi ushlanadi
    main_router.include_routers(
        start.router,
        quiz.router,
        admin.router,
        broadcast.router,
        common.router,
        content.router,
        mocks.router,
        payments.router,
        balance.router,
        student.router,
        tests.router,
        abi_tests.router,
        rating.router,
        mock.router,
        mistakes.router,
        abituriyent.router,
        fallback.router,
    )
    return main_router
