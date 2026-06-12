"""Расчётное ядро. Чистые функции: ни aiogram, ни БД.

Деньги — всегда int (копейки). Сумма всех балансов после расчёта равна нулю.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpenseItem:
    payer_id: int
    type: str        # 'common' | 'daily'
    date: str        # ISO YYYY-MM-DD
    amount: int      # копейки


def _split(amount: int, participants: list[int]) -> dict[int, int]:
    """Делит сумму поровну; остаток копеек детерминированно раздаётся
    первым участникам отсортированного списка (по одному)."""
    n = len(participants)
    base, rest = divmod(amount, n)
    shares: dict[int, int] = {}
    for i, uid in enumerate(sorted(participants)):
        shares[uid] = base + (1 if i < rest else 0)
    return shares


def compute_balances(
    member_ids: list[int],
    expenses: list[ExpenseItem],
    absences: set[tuple[int, str]],
) -> dict[int, int]:
    """Чистый баланс каждого участника.

    > 0 — участнику должны; < 0 — участник должен.
    Правила:
      * common — делится между всеми member_ids;
      * daily  — между присутствовавшими в дату траты; плательщик
        присутствует по определению, даже если отметил отсутствие;
      * если в день daily-траты присутствовал только плательщик —
        трата целиком остаётся на нём (долгов не возникает);
      * плательщик, исключённый из коллектива, в дележе не участвует,
        но кредит за свою трату получает.
    """
    balances: dict[int, int] = {uid: 0 for uid in member_ids}

    for exp in expenses:
        if exp.type == "common":
            participants = list(member_ids)
        else:
            participants = [
                uid for uid in member_ids
                if uid == exp.payer_id or (uid, exp.date) not in absences
            ]

        if not participants:
            # все активные отсутствовали, а плательщик исключён — некому делить
            continue

        balances.setdefault(exp.payer_id, 0)
        balances[exp.payer_id] += exp.amount
        for uid, share in _split(exp.amount, participants).items():
            balances[uid] -= share

    assert sum(balances.values()) == 0, "балансы не сходятся в ноль"
    return balances


def minimize_transfers(balances: dict[int, int]) -> list[tuple[int, int, int]]:
    """Жадная минимизация: (должник, кредитор, сумма). Не более N-1 переводов."""
    debtors = sorted(
        ((uid, -b) for uid, b in balances.items() if b < 0),
        key=lambda x: (-x[1], x[0]))
    creditors = sorted(
        ((uid, b) for uid, b in balances.items() if b > 0),
        key=lambda x: (-x[1], x[0]))

    transfers: list[tuple[int, int, int]] = []
    i = j = 0
    debtors = [list(d) for d in debtors]
    creditors = [list(c) for c in creditors]
    while i < len(debtors) and j < len(creditors):
        debtor, owes = debtors[i]
        creditor, due = creditors[j]
        pay = min(owes, due)
        if pay > 0:
            transfers.append((debtor, creditor, pay))
        debtors[i][1] -= pay
        creditors[j][1] -= pay
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers
