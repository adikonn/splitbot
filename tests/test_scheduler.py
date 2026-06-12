"""Тесты scheduler: идемпотентность месячного джоба, напоминания, конфигурация джобов."""
from db.repositories import ConfirmationRepo, PeriodRepo, SchedulerLogRepo
from scheduler import monthly_settlement_job, reminder_job, setup_scheduler
from tests.conftest import BOB_TG


async def test_monthly_job_starts_settlement(db, seeded, bot):
    await monthly_settlement_job(bot, db)
    assert (await PeriodRepo.get(db, seeded["period"]))["status"] == "confirming"
    assert (await PeriodRepo.by_status(db, "open"))["month"] == 7
    assert len(bot.sent) == 3


async def test_monthly_job_idempotent_for_same_period(db, seeded, bot):
    # ключ периода уже захвачен (бот перезапустился после срабатывания)
    assert await SchedulerLogRepo.try_acquire(db, "settle_2026-06")
    await monthly_settlement_job(bot, db)
    assert (await PeriodRepo.get(db, seeded["period"]))["status"] == "open"
    assert bot.sent == []


async def test_monthly_job_blocked_while_previous_confirming(db, seeded, bot):
    await monthly_settlement_job(bot, db)          # июнь → confirming, июль open
    bot.sent.clear()
    await monthly_settlement_job(bot, db)          # июль не стартует: июнь не закрыт
    july = await PeriodRepo.by_month(db, 2026, 7)
    assert july["status"] == "open"
    assert bot.sent == []
    # ...но после принудительного закрытия июня джоб июля сработает
    await PeriodRepo.to_closed(db, seeded["period"])
    await monthly_settlement_job(bot, db)
    assert (await PeriodRepo.by_month(db, 2026, 7))["status"] == "confirming"


async def test_monthly_job_no_open_period(db, bot):
    await monthly_settlement_job(bot, db)
    assert bot.sent == []


async def test_reminder_job(db, seeded, bot):
    await PeriodRepo.to_confirming(db, seeded["period"])
    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])
    await reminder_job(bot, db)
    assert bot.texts_for(BOB_TG) == []
    assert len(bot.sent) == 2


def test_setup_scheduler_jobs(bot, db, config):
    scheduler = setup_scheduler(bot, db, config)
    ids = {j.id for j in scheduler.get_jobs()}
    assert ids == {"monthly_settlement", "daily_reminder"}
