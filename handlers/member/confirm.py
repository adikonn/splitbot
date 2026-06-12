"""Расчёт глазами участника: статус, превью и кнопка подтверждения."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from db.database import Database
from db.repositories import ConfirmationRepo, ExpenseRepo, PeriodRepo, SettlementRepo
from keyboards.common import BTN_CALC, confirm_calc_kb
from services import period_service
from utils import fmt_money, period_title

router = Router(name="member_confirm")


@router.message(F.text == BTN_CALC)
async def calc_status(message: Message, db: Database, db_user) -> None:
    confirming = await PeriodRepo.by_status(db, "confirming")
    if confirming:
        text = await period_service.build_preview(db, confirming)
        confirmed = await ConfirmationRepo.user_ids(db, confirming["id"])
        kb = None if db_user["id"] in confirmed else confirm_calc_kb(confirming["id"])
        if db_user["id"] in confirmed:
            text += "\n\n✅ Вы уже подтвердили расчёт."
        await message.answer(text, reply_markup=kb)
        return

    open_period = await period_service.ensure_current_period(db)
    expenses = await ExpenseRepo.for_period(db, open_period["id"])
    total = sum(e["amount"] for e in expenses)
    text = (
        f"Период «{period_title(open_period['year'], open_period['month'])}» открыт: "
        f"{len(expenses)} трат на {fmt_money(total)}.\n"
        "Расчёт начнётся автоматически в начале следующего месяца."
    )
    last = await PeriodRepo.last_closed(db)
    if last:
        transfers_rows = await SettlementRepo.for_period(db, last["id"])
        transfers = [(r["from_user"], r["to_user"], r["amount"]) for r in transfers_rows]
        text += (
            f"\n\n🔒 Последний закрытый расчёт — "
            f"{period_title(last['year'], last['month'])}:\n"
            + await period_service.transfers_text(db, last["id"], transfers)
        )
    await message.answer(text)


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_calc(callback: CallbackQuery, db: Database, db_user,
                       bot: Bot) -> None:
    period_id = int(callback.data.split(":")[1])
    period = await PeriodRepo.get(db, period_id)
    if not period or period["status"] != "confirming":
        await callback.answer("Этот расчёт уже закрыт.", show_alert=True)
        return
    await ConfirmationRepo.add(db, period_id, db_user["id"])
    await callback.answer("Подтверждено ✅")
    closed = await period_service.try_close(bot, db, period_id)
    if not closed:
        await callback.message.edit_text(await period_service.build_preview(db, period))
