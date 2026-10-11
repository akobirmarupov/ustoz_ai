import asyncio
import logging
import os

from aiohttp import web
from aiogram.types import BotCommand

from data import config
from database.db import init_db
from database.requests import migrate_orphan_questions
from handlers import setup_handlers
from loader import bot, dp
from middlewares.user import UserMiddleware
from services.worker import run_worker


async def start_web_server() -> web.AppRunner:
    async def health(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_get("/", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("Web server %s portda ishga tushdi", port)
    return runner


async def main() -> None:
    runner = await start_web_server()

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    await migrate_orphan_questions()

    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    dp.include_router(setup_handlers())

    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="testlar", description="Mening testlarim"),
    ])
    worker = asyncio.create_task(run_worker(bot))
    logging.info("Ustoz Elite ishga tushdi...")
    try:
        await dp.start_polling(bot)
    finally:
        worker.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())