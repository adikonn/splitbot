"""Точка входа SplitBot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_config
from db.database import Database
from handlers import start
from handlers.admin import expenses as admin_expenses
from handlers.admin import members as admin_members
from handlers.admin import panel as admin_panel
from handlers.admin import period as admin_period
from handlers.member import absences as member_absences
from handlers.member import confirm as member_confirm
from handlers.member import expenses as member_expenses
from middlewares.access import AccessMiddleware, AdminMiddleware
from scheduler import setup_scheduler
from services.period_service import ensure_current_period

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("splitbot")


def build_dispatcher(db: Database, config) -> Dispatcher:
    """Сборка диспетчера: роутеры и middleware. Вынесена из main() для тестов."""
    dp = Dispatcher()
    dp["db"] = db
    dp["config"] = config

    # --- роутер участников (требует active-статус) ---
    member_router = Router(name="member")
    access = AccessMiddleware(db)
    member_router.message.middleware(access)
    member_router.callback_query.middleware(access)
    member_router.include_routers(
        member_expenses.router, member_absences.router, member_confirm.router)

    # --- админ-роутер (active + role=admin) ---
    admin_router = Router(name="admin")
    admin_router.message.middleware(access)
    admin_router.callback_query.middleware(access)
    admin_router.message.middleware(AdminMiddleware())
    admin_router.callback_query.middleware(AdminMiddleware())
    admin_router.include_routers(
        admin_panel.router, admin_members.router,
        admin_expenses.router, admin_period.router)

    # порядок важен: start не защищён, админ — раньше участников
    dp.include_routers(start.router, admin_router, member_router)
    return dp


async def main() -> None:
    config = load_config()

    db = Database(config.db_path)
    await db.connect()

    bot = Bot(token=config.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(db, config)

    await ensure_current_period(db)

    scheduler = setup_scheduler(bot, db, config)
    scheduler.start()

    log.info("SplitBot запущен")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
