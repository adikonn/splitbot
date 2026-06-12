"""Траты участника: AddExpenseFSM и просмотр своих трат открытого периода."""
from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram_calendar import SimpleCalendarCallback

from db.database import Database
from db.repositories import ExpenseRepo
from keyboards.calendar import bounded_simple_calendar, in_period, start_bounded_calendar
from keyboards.common import (
    BTN_ADD_EXPENSE,
    BTN_MY_EXPENSES,
    cancel_kb,
    expense_confirm_kb,
    expense_type_kb,
    skip_or_cancel_kb,
)
from services.period_service import ensure_current_period
from states.states import AddExpenseFSM
from utils import fmt_date, fmt_money, parse_money, period_title

router = Router(name="member_expenses")

TYPE_LABEL = {"common": "👥 общая (платят все)",
              "daily": "📆 дневная (платят присутствовавшие)"}


def _card(data: dict) -> str:
    return (
        "🧾 <b>Новая трата</b>\n"
        f"Тип: {TYPE_LABEL[data['type']]}\n"
        f"Дата: {fmt_date(data['date'])}\n"
        f"Сумма: {fmt_money(data['amount'])}\n"
        f"Назначение: {data['description'] or '—'}"
    )


@router.message(F.text == BTN_ADD_EXPENSE)
async def add_expense_start(message: Message, state: FSMContext, db: Database) -> None:
    period = await ensure_current_period(db)
    await state.set_state(AddExpenseFSM.choosing_type)
    await state.update_data(period_id=period["id"],
                            year=period["year"], month=period["month"])
    await message.answer(
        f"Трата в период «{period_title(period['year'], period['month'])}».\n"
        "Выберите тип:", reply_markup=expense_type_kb())


@router.callback_query(AddExpenseFSM.choosing_type, F.data.startswith("exp_type:"))
async def choose_type(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(type=callback.data.split(":")[1])
    data = await state.get_data()
    await state.set_state(AddExpenseFSM.choosing_date)
    await callback.message.edit_text(
        "Выберите дату траты:",
        reply_markup=await start_bounded_calendar(data["year"], data["month"]))
    await callback.answer()


@router.callback_query(AddExpenseFSM.choosing_date, SimpleCalendarCallback.filter())
async def choose_date(callback: CallbackQuery, callback_data: SimpleCalendarCallback,
                      state: FSMContext) -> None:
    data = await state.get_data()
    cal = bounded_simple_calendar(data["year"], data["month"])
    selected, chosen = await cal.process_selection(callback, callback_data)
    if not selected:
        return
    chosen_date: date = chosen.date() if hasattr(chosen, "date") else chosen
    if not in_period(chosen_date, data["year"], data["month"]):
        await callback.message.answer(
            "Дата вне расчётного месяца, выберите другую:",
            reply_markup=await start_bounded_calendar(data["year"], data["month"]))
        return
    await state.update_data(date=chosen_date.isoformat())
    await state.set_state(AddExpenseFSM.entering_amount)
    await callback.message.answer(
        f"Дата: {chosen_date.strftime('%d.%m.%Y')}.\n"
        "Введите сумму (например 1250 или 99,90):", reply_markup=cancel_kb())


@router.message(AddExpenseFSM.entering_amount, F.text)
async def enter_amount(message: Message, state: FSMContext) -> None:
    amount = parse_money(message.text)
    if amount is None:
        await message.answer("Не понял сумму. Введите положительное число, "
                             "например 1250 или 99,90:", reply_markup=cancel_kb())
        return
    await state.update_data(amount=amount)
    await state.set_state(AddExpenseFSM.entering_description)
    await message.answer("Назначение траты (например «продукты»)?",
                         reply_markup=skip_or_cancel_kb())


@router.message(AddExpenseFSM.entering_description, F.text)
async def enter_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip()[:200])
    await _show_card(message, state)


@router.callback_query(AddExpenseFSM.entering_description, F.data == "exp_desc:skip")
async def skip_description(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(description="")
    await callback.message.edit_reply_markup(reply_markup=None)
    await _show_card(callback.message, state)
    await callback.answer()


async def _show_card(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(AddExpenseFSM.confirming)
    await message.answer(_card(data), reply_markup=expense_confirm_kb())


@router.callback_query(AddExpenseFSM.confirming, F.data == "exp:save")
async def save_expense(callback: CallbackQuery, state: FSMContext, db: Database,
                       db_user) -> None:
    data = await state.get_data()
    await state.clear()
    await ExpenseRepo.add(db, data["period_id"], db_user["id"], data["type"],
                          data["date"], data["amount"], data["description"])
    await callback.message.edit_text(_card(data) + "\n\n✅ Сохранено.")
    await callback.answer("Трата сохранена")


@router.message(F.text == BTN_MY_EXPENSES)
async def my_expenses(message: Message, db: Database, db_user) -> None:
    period = await ensure_current_period(db)
    rows = await ExpenseRepo.for_user(db, period["id"], db_user["id"])
    title = period_title(period["year"], period["month"])
    if not rows:
        await message.answer(f"В периоде «{title}» у вас пока нет трат.")
        return
    lines = [f"📋 <b>Ваши траты — {title}</b>"]
    total = 0
    for e in rows:
        total += e["amount"]
        t = "👥" if e["type"] == "common" else "📆"
        lines.append(f"{t} {fmt_date(e['date'])} — {fmt_money(e['amount'])}"
                     f" {e['description'] or ''}".rstrip())
    lines.append(f"\nИтого: <b>{fmt_money(total)}</b>")
    await message.answer("\n".join(lines))
