"""Тесты utils: деньги, даты, подписи."""
import pytest

from utils import (
    fmt_date,
    fmt_money,
    month_bounds,
    month_last_day,
    parse_money,
    period_title,
)


@pytest.mark.parametrize("text,expected", [
    ("1250", 125000),
    ("99,90", 9990),
    ("99.9", 9990),
    ("0.01", 1),
    (" 1 000 ", 100000),       # пробелы вычищаются
    ("7,5", 750),
])
def test_parse_money_ok(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", [
    "", "abc", "-5", "1.234", "10,123", "1e3", "0", "0,00", "12.34.56",
])
def test_parse_money_bad(text):
    assert parse_money(text) is None


def test_fmt_money():
    assert fmt_money(125000) == "1250.00"
    assert fmt_money(1) == "0.01"
    assert fmt_money(-9990) == "-99.90"
    assert fmt_money(0) == "0.00"


def test_money_roundtrip():
    for raw in ("1250", "99,90", "0.07"):
        kop = parse_money(raw)
        assert parse_money(fmt_money(kop)) == kop


def test_fmt_date():
    assert fmt_date("2026-06-05") == "05.06.2026"


def test_period_title():
    assert period_title(2026, 6) == "июнь 2026"
    assert period_title(2025, 12) == "декабрь 2025"


def test_month_bounds_and_last_day():
    assert month_last_day(2026, 6) == 30
    assert month_last_day(2024, 2) == 29   # високосный
    first, last = month_bounds(2026, 2)
    assert (first.day, last.day) == (1, 28)
