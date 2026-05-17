"""Точка входа: запуск Telegram-бота и шедулера напоминаний."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from database import db
from handlers import router
from scheduler import start_scheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


async def main() -> None:
    await db.init()
    log.info("База инициализирована: %s", config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=None),  # parse_mode задаём явно на каждое сообщение
    )
    dp = Dispatcher()
    dp.include_router(router)

    sched = start_scheduler(bot)

    try:
        log.info("Запускаю long polling…")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен")
