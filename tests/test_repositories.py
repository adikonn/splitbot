"""Тесты репозиториев: users, periods, expenses, absences, confirmations,
settlements, scheduler_log."""
import pytest

from db.repositories import (
    AbsenceRepo,
    ConfirmationRepo,
    ExpenseRepo,
    PeriodRepo,
    SchedulerLogRepo,
    SettlementRepo,
    UserRepo,
)


# ------------------------------ users ---------------------------------------

async def test_user_create_get(db):
    uid = await UserRepo.create(db, 1, "u", "Имя", "member", "pending")
    by_tg = await UserRepo.get_by_tg(db, 1)
    by_id = await UserRepo.get(db, uid)
    assert by_tg["id"] == by_id["id"] == uid
    assert by_tg["status"] == "pending" and by_tg["role"] == "member"


async def test_user_unique_tg(db):
    await UserRepo.create(db, 1, None, "A", "member", "active")
    with pytest.raises(Exception):
        await UserRepo.create(db, 1, None, "B", "member", "active")


async def test_user_status_and_lists(db, seeded):
    assert {u["full_name"] for u in await UserRepo.active(db)} == {"Админ", "Боб", "Ева"}
    await UserRepo.set_status(db, seeded["bob"], "removed")
    assert len(await UserRepo.active(db)) == 2
    assert await UserRepo.pending(db) == []


async def test_user_reapply(db, seeded):
    await UserRepo.set_status(db, seeded["bob"], "removed")
    await UserRepo.reapply(db, seeded["bob"], "newbob", "Боб 2.0")
    user = await UserRepo.get(db, seeded["bob"])
    assert user["status"] == "pending"
    assert user["full_name"] == "Боб 2.0" and user["username"] == "newbob"


# ------------------------------ periods -------------------------------------

async def test_period_lifecycle(db):
    pid = await PeriodRepo.create_open(db, 2026, 6)
    assert (await PeriodRepo.by_status(db, "open"))["id"] == pid
    assert (await PeriodRepo.by_month(db, 2026, 6))["id"] == pid

    await PeriodRepo.to_confirming(db, pid)
    p = await PeriodRepo.get(db, pid)
    assert p["status"] == "confirming" and p["confirming_at"] is not None
    assert await PeriodRepo.by_status(db, "open") is None

    await PeriodRepo.to_closed(db, pid)
    p = await PeriodRepo.get(db, pid)
    assert p["status"] == "closed" and p["closed_at"] is not None
    assert (await PeriodRepo.last_closed(db))["id"] == pid


async def test_period_unique_month(db):
    await PeriodRepo.create_open(db, 2026, 6)
    with pytest.raises(Exception):
        await PeriodRepo.create_open(db, 2026, 6)


# ------------------------------ expenses ------------------------------------

async def test_expense_crud(db, seeded):
    pid, bob = seeded["period"], seeded["bob"]
    eid = await ExpenseRepo.add(db, pid, bob, "common", "2026-06-01", 100_00, "тест")
    e = await ExpenseRepo.get(db, eid)
    assert e["amount"] == 100_00 and e["payer_name"] == "Боб"
    assert e["updated_at"] is None and e["edited_by"] is None

    await ExpenseRepo.update_field(db, eid, "amount", 200_00, seeded["admin"])
    e = await ExpenseRepo.get(db, eid)
    assert e["amount"] == 200_00
    assert e["edited_by"] == seeded["admin"] and e["updated_at"] is not None

    assert len(await ExpenseRepo.for_period(db, pid)) == 1
    assert len(await ExpenseRepo.for_user(db, pid, bob)) == 1
    assert await ExpenseRepo.for_user(db, pid, seeded["eva"]) == []


async def test_expense_update_field_whitelist(db, seeded):
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 1, "")
    with pytest.raises(AssertionError):
        await ExpenseRepo.update_field(db, eid, "deleted; DROP TABLE users", 1, 1)


async def test_expense_soft_delete(db, seeded):
    pid = seeded["period"]
    eid = await ExpenseRepo.add(db, pid, seeded["bob"], "common", "2026-06-01", 1_00, "")
    await ExpenseRepo.soft_delete(db, eid, seeded["admin"])
    assert await ExpenseRepo.for_period(db, pid) == []
    assert (await ExpenseRepo.get(db, eid))["deleted"] == 1  # строка сохранена


# ------------------------------ absences ------------------------------------

async def test_absences_replace_and_read(db, seeded):
    pid, bob = seeded["period"], seeded["bob"]
    await AbsenceRepo.replace_for_user(db, pid, bob, {"2026-06-05", "2026-06-06"})
    assert await AbsenceRepo.days_of_user(db, pid, bob) == {"2026-06-05", "2026-06-06"}

    await AbsenceRepo.replace_for_user(db, pid, bob, {"2026-06-07"})  # полная замена
    assert await AbsenceRepo.days_of_user(db, pid, bob) == {"2026-06-07"}
    assert await AbsenceRepo.for_period(db, pid) == {(bob, "2026-06-07")}

    await AbsenceRepo.replace_for_user(db, pid, bob, set())           # очистка
    assert await AbsenceRepo.days_of_user(db, pid, bob) == set()


# ------------------------------ confirmations -------------------------------

async def test_confirmations(db, seeded):
    pid = seeded["period"]
    await ConfirmationRepo.add(db, pid, seeded["bob"])
    await ConfirmationRepo.add(db, pid, seeded["bob"])  # идемпотентно
    assert await ConfirmationRepo.user_ids(db, pid) == {seeded["bob"]}
    await ConfirmationRepo.reset(db, pid)
    assert await ConfirmationRepo.user_ids(db, pid) == set()


# ------------------------------ settlements ---------------------------------

async def test_settlements_save_overwrites(db, seeded):
    pid = seeded["period"]
    await SettlementRepo.save(db, pid, [(seeded["bob"], seeded["admin"], 50_00)])
    await SettlementRepo.save(db, pid, [(seeded["eva"], seeded["admin"], 70_00)])
    rows = await SettlementRepo.for_period(db, pid)
    assert len(rows) == 1
    assert rows[0]["from_name"] == "Ева" and rows[0]["to_name"] == "Админ"
    assert rows[0]["amount"] == 70_00


# ------------------------------ scheduler_log -------------------------------

async def test_scheduler_log_acquire_once(db):
    assert await SchedulerLogRepo.try_acquire(db, "settle_2026-06") is True
    assert await SchedulerLogRepo.try_acquire(db, "settle_2026-06") is False
    assert await SchedulerLogRepo.try_acquire(db, "settle_2026-07") is True
