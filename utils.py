"""Утилиты: деньги (int, копейки), даты, форматирование."""
from __future__ import annotations

import calendar as _cal
import re
from datetime import date, datetime

MONTHS_RU = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]

_MONEY_RE = re.compile(r"^\d{1,9}([.,]\d{1,2})?$")


def parse_money(text: str) -> int | None:
    """'1234,5' -> 123450 копеек. None, если ввод некорректен или ноль."""
    text = text.strip().replace(" ", "")
    if not _MONEY_RE.match(text):
        return None
    text = text.replace(",", ".")
    if "." in text:
        rub, kop = text.split(".")
        kop = (kop + "00")[:2]
    else:
        rub, kop = text, "00"
    value = int(rub) * 100 + int(kop)
    return value or None


def fmt_money(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else ""
    kopecks = abs(kopecks)
    return f"{sign}{kopecks // 100}.{kopecks % 100:02d}"


def fmt_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def period_title(year: int, month: int) -> str:
    return f"{MONTHS_RU[month]} {year}"


def month_last_day(year: int, month: int) -> int:
    return _cal.monthrange(year, month)[1]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, month_last_day(year, month))


def user_label(user) -> str:
    """Имя участника для текстов; user — sqlite3.Row из таблицы users."""
    name = user["full_name"] or (f"@{user['username']}" if user["username"] else f"id{user['tg_id']}")
    return name
