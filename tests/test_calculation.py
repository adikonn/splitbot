"""Тесты расчётного ядра: python -m pytest tests/ -q (или python tests/test_calculation.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.calculation import ExpenseItem, compute_balances, minimize_transfers


def test_common_split_even():
    members = [1, 2, 3]
    exps = [ExpenseItem(payer_id=1, type="common", date="2026-06-01", amount=300)]
    b = compute_balances(members, exps, set())
    assert b == {1: 200, 2: -100, 3: -100}


def test_common_split_remainder_deterministic():
    members = [1, 2, 3]
    exps = [ExpenseItem(payer_id=1, type="common", date="2026-06-01", amount=100)]
    b = compute_balances(members, exps, set())
    # 100 / 3 = 34 + 33 + 33; лишняя копейка первому по id
    assert sum(b.values()) == 0
    assert b[1] == 100 - 34 and b[2] == -33 and b[3] == -33


def test_daily_excludes_absent():
    members = [1, 2, 3]
    exps = [ExpenseItem(payer_id=1, type="daily", date="2026-06-10", amount=200)]
    absences = {(3, "2026-06-10")}
    b = compute_balances(members, exps, absences)
    assert b == {1: 100, 2: -100, 3: 0}


def test_payer_present_even_if_marked_absent():
    members = [1, 2]
    exps = [ExpenseItem(payer_id=1, type="daily", date="2026-06-10", amount=200)]
    absences = {(1, "2026-06-10")}
    b = compute_balances(members, exps, absences)
    assert b == {1: 100, 2: -100}


def test_daily_only_payer_present():
    members = [1, 2, 3]
    exps = [ExpenseItem(payer_id=1, type="daily", date="2026-06-10", amount=500)]
    absences = {(2, "2026-06-10"), (3, "2026-06-10")}
    b = compute_balances(members, exps, absences)
    assert b == {1: 0, 2: 0, 3: 0}  # трата целиком на плательщике


def test_removed_payer_gets_credit():
    members = [2, 3]  # плательщик 1 исключён из коллектива
    exps = [ExpenseItem(payer_id=1, type="common", date="2026-06-01", amount=200)]
    b = compute_balances(members, exps, set())
    assert b == {1: 200, 2: -100, 3: -100}


def test_minimize_transfers_count():
    balances = {1: 300, 2: -100, 3: -100, 4: -100}
    tr = minimize_transfers(balances)
    assert len(tr) <= 3
    assert sum(a for _, _, a in tr) == 300
    assert all(t == 1 for _, t, _ in tr)


def test_minimize_transfers_chain():
    # 1 должен 50, 2 должен 50, 3 ждёт 100 → ровно 2 перевода
    balances = {1: -50, 2: -50, 3: 100}
    tr = minimize_transfers(balances)
    assert sorted(tr) == [(1, 3, 50), (2, 3, 50)]


def test_complex_month():
    members = [1, 2, 3, 4]
    exps = [
        ExpenseItem(1, "common", "2026-06-01", 120_00),
        ExpenseItem(2, "daily", "2026-06-05", 90_00),
        ExpenseItem(3, "daily", "2026-06-05", 30_01),
        ExpenseItem(4, "common", "2026-06-20", 7),
    ]
    absences = {(4, "2026-06-05"), (1, "2026-06-05")}
    b = compute_balances(members, exps, absences)
    assert sum(b.values()) == 0
    tr = minimize_transfers(b)
    assert len(tr) <= len(members) - 1
    # после переводов все балансы гасятся
    for f, t, a in tr:
        b[f] += a
        b[t] -= a
    assert all(v == 0 for v in b.values())


if __name__ == "__main__":
    g = dict(globals())
    for name, fn in g.items():
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")
    print("Все тесты пройдены.")
