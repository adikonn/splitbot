"""Жизненный цикл расчётного периода.

open ──(месячный джоб или админ)──▶ confirming ──(все подтвердили / админ)──▶ closed
При старте confirming сразу открывается период нового месяца, поэтому ввод трат
не прерывается. Правка траты в confirming сбрасывает подтверждения.
"""
from __future__ import annotations

import logging
from datetime import date

import aiosqlite
from aiogram import Bot

from db.database import Database
from db.repositories import (
    AbsenceRepo,
    ConfirmationRepo,
    ExpenseRepo,
    PeriodRepo,
    SettlementRepo,
    UserRepo,
)
from keyboards.common import confirm_calc_kb
from services.calculation import ExpenseItem, compute_balances, minimize_transfers
from services.notifications import broadcast, send_safe
from utils import fmt_money, period_title

log = logging.getLogger(__name__)


async def ensure_current_period(db: Database) -> aiosqlite.Row:
    """Гарантирует существование open-периода (создаёт за текущий месяц)."""
    period = await PeriodRepo.by_status(db, "open")
    if period:
        return period
    today = date.today()
    existing = await PeriodRepo.by_month(db, today.year, today.month)
    if existing:  # период месяца уже confirming/closed — открываем следующий
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    else:
        y, m = today.year, today.month
    pid = await PeriodRepo.create_open(db, y, m)
    log.info("Открыт период %s-%02d (id=%s)", y, m, pid)
    return await PeriodRepo.get(db, pid)


# --------------------------- расчёт ----------------------------------------

async def calc_transfers(db: Database, period_id: int) -> list[tuple[int, int, int]]:
    members = [u["id"] for u in await UserRepo.active(db)]
    expenses = [
        ExpenseItem(payer_id=e["payer_id"], type=e["type"],
                    date=e["date"], amount=e["amount"])
        for e in await ExpenseRepo.for_period(db, period_id)
    ]
    absences = await AbsenceRepo.for_period(db, period_id)
    balances = compute_balances(members, expenses, absences)
    return minimize_transfers(balances)


async def transfers_text(db: Database, period_id: int,
                         transfers: list[tuple[int, int, int]]) -> str:
    """Таблица «Кто | Кому | Сколько» моноширинным блоком."""
    if not transfers:
        return "Все в расчёте — переводы не требуются. 🎉"
    names: dict[int, str] = {}
    for f, t, _ in transfers:
        for uid in (f, t):
            if uid not in names:
                u = await UserRepo.get(db, uid)
                names[uid] = u["full_name"] if u else f"id{uid}"
    w1 = max(len("Кто"), *(len(names[f]) for f, _, _ in transfers))
    w2 = max(len("Кому"), *(len(names[t]) for _, t, _ in transfers))
    lines = [f"{'Кто':<{w1}} | {'Кому':<{w2}} | Сколько",
             f"{'-' * w1}-+-{'-' * w2}-+--------"]
    for f, t, a in transfers:
        lines.append(f"{names[f]:<{w1}} | {names[t]:<{w2}} | {fmt_money(a)}")
    return "<pre>" + "\n".join(lines) + "</pre>"


async def build_preview(db: Database, period) -> str:
    transfers = await calc_transfers(db, period["id"])
    expenses = await ExpenseRepo.for_period(db, period["id"])
    total = sum(e["amount"] for e in expenses)
    confirmed = await ConfirmationRepo.user_ids(db, period["id"])
    active = await UserRepo.active(db)
    waiting = [u["full_name"] for u in active if u["id"] not in confirmed]
    text = (
        f"🧮 <b>Расчёт за {period_title(period['year'], period['month'])}</b>\n"
        f"Трат: {len(expenses)} на сумму {fmt_money(total)}\n\n"
        f"{await transfers_text(db, period['id'], transfers)}\n\n"
        f"Подтвердили: {len(confirmed)} из {len(active)}"
    )
    if waiting:
        text += "\nОжидаем: " + ", ".join(waiting)
    return text


# --------------------------- переходы --------------------------------------

async def start_settlement(bot: Bot, db: Database) -> bool:
    """open → confirming; открывает следующий период; рассылает превью.

    False — если перехода не было (нет open-периода или прошлый расчёт не закрыт).
    """
    if await PeriodRepo.by_status(db, "confirming"):
        log.warning("Старт расчёта пропущен: предыдущий период не закрыт")
        return False
    period = await PeriodRepo.by_status(db, "open")
    if not period:
        return False

    await PeriodRepo.to_confirming(db, period["id"])
    # сразу открываем следующий месяц, чтобы ввод трат не останавливался
    y, m = (period["year"] + 1, 1) if period["month"] == 12 else \
           (period["year"], period["month"] + 1)
    if not await PeriodRepo.by_month(db, y, m):
        await PeriodRepo.create_open(db, y, m)

    period = await PeriodRepo.get(db, period["id"])
    text = (
        f"📣 <b>Начался расчёт за {period_title(period['year'], period['month'])}!</b>\n"
        "Проверьте свои траты и даты отсутствия. Если всё верно — подтвердите расчёт.\n"
        "Изменить траты закрытого месяца теперь может только администратор.\n\n"
        + await build_preview(db, period)
    )
    await broadcast(bot, db, text, confirm_calc_kb(period["id"]))
    log.info("Период id=%s переведён в confirming", period["id"])
    return True


async def try_close(bot: Bot, db: Database, period_id: int) -> bool:
    """Закрывает период, если подтвердили все активные участники."""
    confirmed = await ConfirmationRepo.user_ids(db, period_id)
    active_ids = {u["id"] for u in await UserRepo.active(db)}
    if not active_ids or not active_ids.issubset(confirmed):
        return False
    await close_period(bot, db, period_id, forced=False)
    return True


async def close_period(bot: Bot, db: Database, period_id: int, forced: bool) -> None:
    period = await PeriodRepo.get(db, period_id)
    transfers = await calc_transfers(db, period_id)
    await SettlementRepo.save(db, period_id, transfers)
    await PeriodRepo.to_closed(db, period_id)
    title = period_title(period["year"], period["month"])
    head = (f"🔒 <b>Расчёт за {title} закрыт"
            f"{' администратором' if forced else ''}.</b>\nИтоговые переводы:\n\n")
    await broadcast(bot, db, head + await transfers_text(db, period_id, transfers))
    log.info("Период id=%s закрыт (forced=%s)", period_id, forced)


async def on_expense_changed(bot: Bot, db: Database, period_id: int,
                             editor_name: str) -> None:
    """После правки траты админом: в confirming сбрасываем подтверждения
    и рассылаем обновлённый расчёт."""
    period = await PeriodRepo.get(db, period_id)
    if not period or period["status"] != "confirming":
        return
    await ConfirmationRepo.reset(db, period_id)
    text = (
        f"✏️ Администратор ({editor_name}) изменил траты периода — "
        "подтверждения сброшены, проверьте обновлённый расчёт.\n\n"
        + await build_preview(db, period)
    )
    await broadcast(bot, db, text, confirm_calc_kb(period_id))


async def remind_unconfirmed(bot: Bot, db: Database) -> None:
    period = await PeriodRepo.by_status(db, "confirming")
    if not period:
        return
    confirmed = await ConfirmationRepo.user_ids(db, period["id"])
    title = period_title(period["year"], period["month"])
    for u in await UserRepo.active(db):
        if u["id"] in confirmed:
            continue
        await send_safe(
            bot, u["tg_id"],
            f"⏰ Напоминание: расчёт за {title} ждёт вашего подтверждения "
            f"(кнопка «{'📊 Расчёт'}» в меню).",
        )
