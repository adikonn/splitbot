"""Тесты period_service: переходы периода, превью, закрытие, сброс подтверждений,
напоминания, текст таблицы."""
from datetime import date

from db.repositories import (
    AbsenceRepo,
    ConfirmationRepo,
    ExpenseRepo,
    PeriodRepo,
    SettlementRepo,
    UserRepo,
)
from services import period_service
from tests.conftest import ADMIN_TG, BOB_TG, EVA_TG


async def _seed_expenses(db, s):
    # Аренда 300: каждый должен Админу по 100 (он сам — себе)
    await ExpenseRepo.add(db, s["period"], s["admin"], "common",
                          "2026-06-01", 300_00, "аренда")
    # Такси 90 в день, когда Евы не было: делят Админ и Боб
    await ExpenseRepo.add(db, s["period"], s["bob"], "daily",
                          "2026-06-05", 90_00, "такси")
    await AbsenceRepo.replace_for_user(db, s["period"], s["eva"], {"2026-06-05"})


# ------------------------- ensure_current_period ----------------------------

async def test_ensure_returns_existing_open(db, seeded):
    p = await period_service.ensure_current_period(db)
    assert p["id"] == seeded["period"]


async def test_ensure_creates_for_today(db):
    p = await period_service.ensure_current_period(db)
    today = date.today()
    assert (p["year"], p["month"], p["status"]) == (today.year, today.month, "open")


async def test_ensure_opens_next_month_if_current_closed(db):
    today = date.today()
    pid = await PeriodRepo.create_open(db, today.year, today.month)
    await PeriodRepo.to_closed(db, pid)
    p = await period_service.ensure_current_period(db)
    expected = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    assert (p["year"], p["month"]) == expected and p["status"] == "open"


# ------------------------- расчёт и таблица ---------------------------------

async def test_calc_transfers(db, seeded):
    await _seed_expenses(db, seeded)
    transfers = await period_service.calc_transfers(db, seeded["period"])
    as_dict = {(f, t): a for f, t, a in transfers}
    # Боб: -100 (аренда) +45 (такси) = должен 55; Ева: -100
    assert as_dict == {
        (seeded["eva"], seeded["admin"]): 100_00,
        (seeded["bob"], seeded["admin"]): 55_00,
    }


async def test_transfers_text_table(db, seeded):
    await _seed_expenses(db, seeded)
    transfers = await period_service.calc_transfers(db, seeded["period"])
    text = await period_service.transfers_text(db, seeded["period"], transfers)
    assert text.startswith("<pre>") and text.endswith("</pre>")
    assert "Кто" in text and "Кому" in text and "Сколько" in text
    assert "Боб" in text and "55.00" in text and "100.00" in text


async def test_transfers_text_empty(db, seeded):
    text = await period_service.transfers_text(db, seeded["period"], [])
    assert "переводы не требуются" in text


async def test_build_preview(db, seeded):
    await _seed_expenses(db, seeded)
    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])
    period = await PeriodRepo.get(db, seeded["period"])
    text = await period_service.build_preview(db, period)
    assert "июнь 2026" in text
    assert "Трат: 2" in text and "390.00" in text
    assert "Подтвердили: 1 из 3" in text
    assert "Ожидаем: Админ, Ева" in text


# ------------------------- start_settlement ---------------------------------

async def test_start_settlement(db, seeded, bot):
    await _seed_expenses(db, seeded)
    assert await period_service.start_settlement(bot, db) is True

    assert (await PeriodRepo.get(db, seeded["period"]))["status"] == "confirming"
    nxt = await PeriodRepo.by_status(db, "open")          # следующий месяц открыт
    assert (nxt["year"], nxt["month"]) == (2026, 7)

    assert len(bot.sent) == 3                             # превью всем активным
    assert "Начался расчёт" in bot.texts_for(BOB_TG)[0]
    assert bot.markup_for(BOB_TG)[0] is not None          # кнопка подтверждения


async def test_start_settlement_december_rollover(db, bot):
    await UserRepo.create(db, ADMIN_TG, None, "Админ", "admin", "active")
    await PeriodRepo.create_open(db, 2026, 12)
    assert await period_service.start_settlement(bot, db) is True
    nxt = await PeriodRepo.by_status(db, "open")
    assert (nxt["year"], nxt["month"]) == (2027, 1)


async def test_start_settlement_blocked_by_unclosed(db, seeded, bot):
    assert await period_service.start_settlement(bot, db) is True
    bot.sent.clear()
    # период 2026-07 открыт, но 2026-06 ещё confirming — второй запуск запрещён
    assert await period_service.start_settlement(bot, db) is False
    assert bot.sent == []


async def test_start_settlement_without_open_period(db, bot):
    assert await period_service.start_settlement(bot, db) is False


# ------------------------- закрытие -----------------------------------------

async def test_try_close_waits_for_everyone(db, seeded, bot):
    await _seed_expenses(db, seeded)
    await PeriodRepo.to_confirming(db, seeded["period"])
    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])
    assert await period_service.try_close(bot, db, seeded["period"]) is False
    assert (await PeriodRepo.get(db, seeded["period"]))["status"] == "confirming"

    for uid in (seeded["admin"], seeded["eva"]):
        await ConfirmationRepo.add(db, seeded["period"], uid)
    assert await period_service.try_close(bot, db, seeded["period"]) is True

    period = await PeriodRepo.get(db, seeded["period"])
    assert period["status"] == "closed"
    assert len(await SettlementRepo.for_period(db, seeded["period"])) == 2
    final = bot.texts_for(EVA_TG)[-1]
    assert "закрыт" in final and "<pre>" in final


async def test_force_close_mentions_admin(db, seeded, bot):
    await PeriodRepo.to_confirming(db, seeded["period"])
    await period_service.close_period(bot, db, seeded["period"], forced=True)
    assert "закрыт администратором" in bot.texts_for(BOB_TG)[0]


async def test_broadcast_survives_blocked_user(db, seeded, bot):
    bot.fail_for.add(BOB_TG)
    await PeriodRepo.to_confirming(db, seeded["period"])
    await period_service.close_period(bot, db, seeded["period"], forced=False)
    assert bot.texts_for(BOB_TG) == []          # упал — но не уронил рассылку
    assert bot.texts_for(EVA_TG) and bot.texts_for(ADMIN_TG)


# ------------------------- правка в confirming -------------------------------

async def test_on_expense_changed_resets_confirmations(db, seeded, bot):
    await _seed_expenses(db, seeded)
    await PeriodRepo.to_confirming(db, seeded["period"])
    for uid in (seeded["bob"], seeded["eva"]):
        await ConfirmationRepo.add(db, seeded["period"], uid)

    await period_service.on_expense_changed(bot, db, seeded["period"], "Админ")
    assert await ConfirmationRepo.user_ids(db, seeded["period"]) == set()
    msg = bot.texts_for(BOB_TG)[0]
    assert "подтверждения сброшены" in msg and "Админ" in msg


async def test_on_expense_changed_noop_for_open(db, seeded, bot):
    await period_service.on_expense_changed(bot, db, seeded["period"], "Админ")
    assert bot.sent == []


# ------------------------- напоминания --------------------------------------

async def test_remind_unconfirmed_only(db, seeded, bot):
    await PeriodRepo.to_confirming(db, seeded["period"])
    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])
    await period_service.remind_unconfirmed(bot, db)
    assert bot.texts_for(BOB_TG) == []
    assert len(bot.texts_for(ADMIN_TG)) == 1 and len(bot.texts_for(EVA_TG)) == 1
    assert "Напоминание" in bot.texts_for(EVA_TG)[0]


async def test_remind_noop_without_confirming(db, seeded, bot):
    await period_service.remind_unconfirmed(bot, db)
    assert bot.sent == []
