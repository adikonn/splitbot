"""Планировщик (APScheduler).

* Ежемесячно (SETTLE_DAY, SETTLE_HOUR): перевод open → confirming + уведомление.
  Идемпотентность через scheduler_log: перезапуск бота не даст дубля.
* Ежедневно (REMIND_HOUR): напоминание не подтвердившим расчёт.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from db.database import Database
from db.repositories import PeriodRepo, SchedulerLogRepo
from services import period_service

log = logging.getLogger(__name__)


async def monthly_settlement_job(bot: Bot, db: Database) -> None:
    period = await PeriodRepo.by_status(db, "open")
    if not period:
        return
    key = f"settle_{period['year']}-{period['month']:02d}"
    if await SchedulerLogRepo.was_executed(db, key):
        log.info("Джоб %s уже выполнялся — пропуск", key)
        return
    started = await period_service.start_settlement(bot, db)
    if started:
        # фиксируем ключ ТОЛЬКО при успехе: если старт заблокирован незакрытым
        # прошлым расчётом, следующий запуск джоба попробует снова
        await SchedulerLogRepo.try_acquire(db, key)
    else:
        log.warning("Месячный расчёт не стартовал (предыдущий не закрыт?)")


async def reminder_job(bot: Bot, db: Database) -> None:
    await period_service.remind_unconfirmed(bot, db)


def setup_scheduler(bot: Bot, db: Database, config: Config) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.timezone)
    scheduler.add_job(
        monthly_settlement_job, "cron",
        day=config.settle_day, hour=config.settle_hour, minute=0,
        args=(bot, db), id="monthly_settlement",
        misfire_grace_time=6 * 3600,  # бот был выключен в момент срабатывания — догоним
    )
    scheduler.add_job(
        reminder_job, "cron",
        hour=config.remind_hour, minute=0,
        args=(bot, db), id="daily_reminder",
        misfire_grace_time=3600,
    )
    return scheduler
