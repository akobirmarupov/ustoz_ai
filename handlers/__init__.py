from aiogram import F, Router

from handlers.admin import admin, broadcast, content, mocks
from handlers.users import (abi_tests, abituriyent, balance, common, fallback, group_mock, group_quiz, mistakes, mock,
                            payments, quiz, rating, start, student, tests)


def setup_handlers() -> Router:
    main_router = Router()
    # Guruhlar: faqat guruhda test o'tkazish. Qolgan hamma narsa — faqat shaxsiy chatda
    # (aks holda guruhdagi xabarlarga menyu, ro'yxatdan o'tish va h.k. javob berib yuboradi).
    private = Router()
    private.message.filter(F.chat.type == "private")
    # Tartib muhim: «Bekor qilish» va admin buyruqlari har qanday holatda birinchi ushlanadi
    private.include_routers(
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
        group_mock.router,
        mistakes.router,
        abituriyent.router,
        fallback.router,
    )
    main_router.include_routers(group_quiz.router, private)
    return main_router
