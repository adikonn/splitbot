"""Календари.

* Одиночная дата (дата траты, правка даты админом) — aiogram_calendar.SimpleCalendar,
  ограниченный месяцем периода через set_dates_range.
* Мультивыбор дат отсутствия — собственная inline-сетка одного месяца
  (aiogram_calendar мультивыбор не поддерживает).
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram_calendar import SimpleCalendar

from keyboards.common import BTN_CANCEL
from utils import month_bounds

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def bounded_simple_calendar(year: int, month: int) -> SimpleCalendar:
    """SimpleCalendar, в котором можно выбрать дату только внутри месяца периода."""
    cal = SimpleCalendar(show_alerts=True)
    first, last = month_bounds(year, month)
    cal.set_dates_range(
        datetime(first.year, first.month, first.day),
        datetime(last.year, last.month, last.day, 23, 59, 59),
    )
    return cal


async def start_bounded_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    return await bounded_simple_calendar(year, month).start_calendar(year=year, month=month)


def in_period(d: date, year: int, month: int) -> bool:
    return d.year == year and d.month == month


# --------------------- мультивыбор (отсутствия) -----------------------------

def multiselect_month_kb(year: int, month: int, selected: set[int]) -> InlineKeyboardMarkup:
    """Сетка месяца: тап по дню переключает отметку ✓.

    callback_data: abs:toggle:<day> | abs:done | abs:clear | fsm:cancel
    """
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=w, callback_data="abs:noop") for w in WEEKDAYS]
    ]
    for week in _cal.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="abs:noop"))
            else:
                mark = "✅" if day in selected else ""
                row.append(InlineKeyboardButton(
                    text=f"{mark}{day}", callback_data=f"abs:toggle:{day}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="🧹 Очистить", callback_data="abs:clear"),
        InlineKeyboardButton(text="✔️ Готово", callback_data="abs:done"),
    ])
    rows.append([InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
