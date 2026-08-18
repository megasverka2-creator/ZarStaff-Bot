"""Kirish nuqtasi."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("zarstaff")


async def main() -> None:
    settings.validate()

    from bot.db import close_db, init_db
    from bot.handlers import routers

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    for r in routers:
        dp.include_router(r)

    me = await bot.get_me()
    log.info("Ishchi bot ishga tushdi: @%s", me.username)
    log.info("Ruxsat berilgan: %s", settings.allowed_users)
    log.info("Kunlik limit: $%.2f", settings.daily_limit_usd)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("To'xtatildi")
    except RuntimeError as e:
        log.error("\n%s", e)
        raise SystemExit(1)
