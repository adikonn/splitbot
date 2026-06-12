"""Отсутствия участника: AbsenceFSM с мультивыбором дат одного месяца."""
from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db.database import Database
from db.repositories import AbsenceRepo
from keyboards.calendar import multiselect_month_kb
from keyboards.common import BTN_ABSENCES, absence_confirm_kb
from services.period_service import ensure_current_period
from states.states import AbsenceFSM
from utils import period_title

router = Router(name="member_absences")


def _prompt(year: int, month: int) -> str:
    return (f"📅 <b>Отсутствия — {period_title(year, month)}</b>\n"
            "Отметьте дни, когда вас не было (повторный тап снимает отметку), "
            "затем нажмите «Готово».")


@router.message(F.text == BTN_ABSENCES)
async def absences_start(message: Message, state: FSMContext, db: Database,
                         db_user) -> None:
    period = await ensure_current_period(db)
    existing = await AbsenceRepo.days_of_user(db, period["id"], db_user["id"])
    selected = sorted(date.fromisoformat(d).day for d in existing)
    await state.set_state(AbsenceFSM.picking_dates)
    await state.update_data(period_id=period["id"], year=period["year"],
                            month=period["month"], selected=selected)
    await message.answer(
        _prompt(period["year"], period["month"]),
        reply_markup=multiselect_month_kb(period["year"], period["month"], set(selected)))


@router.callback_query(AbsenceFSM.picking_dates, F.data == "abs:noop")
async def abs_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(AbsenceFSM.picking_dates, F.data.startswith("abs:toggle:"))
async def abs_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    day = int(callback.data.split(":")[2])
    data = await state.get_data()
    selected = set(data["selected"])
    selected.symmetric_difference_update({day})
    await state.update_data(selected=sorted(selected))
    await callback.message.edit_reply_markup(
        reply_markup=multiselect_month_kb(data["year"], data["month"], selected))
    await callback.answer()


@router.callback_query(AbsenceFSM.picking_dates, F.data == "abs:clear")
async def abs_clear(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(selected=[])
    await callback.message.edit_reply_markup(
        reply_markup=multiselect_month_kb(data["year"], data["month"], set()))
    await callback.answer("Очищено")


@router.callback_query(AbsenceFSM.picking_dates, F.data == "abs:done")
async def abs_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(AbsenceFSM.confirming)
    days = data["selected"]
    text = (f"Вы отметили отсутствие в дни: <b>{', '.join(map(str, days))}</b>\n"
            f"({period_title(data['year'], data['month'])})"
            if days else "Список отсутствий пуст — вы были все дни месяца.")
    await callback.message.edit_text(text + "\n\nСохранить?",
                                     reply_markup=absence_confirm_kb())
    await callback.answer()


@router.callback_query(AbsenceFSM.confirming, F.data == "abs:back")
async def abs_back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(AbsenceFSM.picking_dates)
    await callback.message.edit_text(
        _prompt(data["year"], data["month"]),
        reply_markup=multiselect_month_kb(data["year"], data["month"],
                                          set(data["selected"])))
    await callback.answer()


@router.callback_query(AbsenceFSM.confirming, F.data == "abs:save")
async def abs_save(callback: CallbackQuery, state: FSMContext, db: Database,
                   db_user) -> None:
    data = await state.get_data()
    await state.clear()
    dates = {date(data["year"], data["month"], d).isoformat() for d in data["selected"]}
    await AbsenceRepo.replace_for_user(db, data["period_id"], db_user["id"], dates)
    await callback.message.edit_text(
        f"✅ Сохранено: {len(dates)} дн. отсутствия в "
        f"{period_title(data['year'], data['month'])}.")
    await callback.answer("Сохранено")
