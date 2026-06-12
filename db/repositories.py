"""Репозитории: весь SQL живёт здесь. Хэндлеры и сервисы работают только через эти функции."""
from __future__ import annotations

import aiosqlite

from db.database import Database
from utils import now_iso


# ----------------------------- users ---------------------------------------

class UserRepo:
    @staticmethod
    async def get_by_tg(db: Database, tg_id: int) -> aiosqlite.Row | None:
        return await db.fetchone("SELECT * FROM users WHERE tg_id = ?", (tg_id,))

    @staticmethod
    async def get(db: Database, user_id: int) -> aiosqlite.Row | None:
        return await db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    @staticmethod
    async def create(db: Database, tg_id: int, username: str | None,
                     full_name: str, role: str, status: str) -> int:
        cur = await db.execute(
            "INSERT INTO users (tg_id, username, full_name, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tg_id, username, full_name, role, status, now_iso()),
        )
        return cur.lastrowid

    @staticmethod
    async def set_status(db: Database, user_id: int, status: str) -> None:
        await db.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))

    @staticmethod
    async def reapply(db: Database, user_id: int, username: str | None, full_name: str) -> None:
        await db.execute(
            "UPDATE users SET status = 'pending', username = ?, full_name = ?, created_at = ? "
            "WHERE id = ?",
            (username, full_name, now_iso(), user_id),
        )

    @staticmethod
    async def active(db: Database) -> list[aiosqlite.Row]:
        return await db.fetchall(
            "SELECT * FROM users WHERE status = 'active' ORDER BY full_name COLLATE NOCASE")

    @staticmethod
    async def pending(db: Database) -> list[aiosqlite.Row]:
        return await db.fetchall(
            "SELECT * FROM users WHERE status = 'pending' ORDER BY created_at")


# ----------------------------- periods -------------------------------------

class PeriodRepo:
    @staticmethod
    async def get(db: Database, period_id: int) -> aiosqlite.Row | None:
        return await db.fetchone("SELECT * FROM periods WHERE id = ?", (period_id,))

    @staticmethod
    async def by_status(db: Database, status: str) -> aiosqlite.Row | None:
        return await db.fetchone(
            "SELECT * FROM periods WHERE status = ? ORDER BY year, month LIMIT 1", (status,))

    @staticmethod
    async def by_month(db: Database, year: int, month: int) -> aiosqlite.Row | None:
        return await db.fetchone(
            "SELECT * FROM periods WHERE year = ? AND month = ?", (year, month))

    @staticmethod
    async def create_open(db: Database, year: int, month: int) -> int:
        cur = await db.execute(
            "INSERT INTO periods (year, month, status, opened_at) VALUES (?, ?, 'open', ?)",
            (year, month, now_iso()),
        )
        return cur.lastrowid

    @staticmethod
    async def to_confirming(db: Database, period_id: int) -> None:
        await db.execute(
            "UPDATE periods SET status = 'confirming', confirming_at = ? WHERE id = ?",
            (now_iso(), period_id),
        )

    @staticmethod
    async def to_closed(db: Database, period_id: int) -> None:
        await db.execute(
            "UPDATE periods SET status = 'closed', closed_at = ? WHERE id = ?",
            (now_iso(), period_id),
        )

    @staticmethod
    async def last_closed(db: Database) -> aiosqlite.Row | None:
        return await db.fetchone(
            "SELECT * FROM periods WHERE status = 'closed' ORDER BY year DESC, month DESC LIMIT 1")


# ----------------------------- expenses ------------------------------------

class ExpenseRepo:
    @staticmethod
    async def add(db: Database, period_id: int, payer_id: int, type_: str,
                  date_iso: str, amount: int, description: str) -> int:
        cur = await db.execute(
            "INSERT INTO expenses (period_id, payer_id, type, date, amount, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (period_id, payer_id, type_, date_iso, amount, description, now_iso()),
        )
        return cur.lastrowid

    @staticmethod
    async def get(db: Database, expense_id: int) -> aiosqlite.Row | None:
        return await db.fetchone(
            "SELECT e.*, u.full_name AS payer_name FROM expenses e "
            "JOIN users u ON u.id = e.payer_id WHERE e.id = ?", (expense_id,))

    @staticmethod
    async def for_period(db: Database, period_id: int) -> list[aiosqlite.Row]:
        return await db.fetchall(
            "SELECT e.*, u.full_name AS payer_name FROM expenses e "
            "JOIN users u ON u.id = e.payer_id "
            "WHERE e.period_id = ? AND e.deleted = 0 ORDER BY e.date, e.id", (period_id,))

    @staticmethod
    async def for_user(db: Database, period_id: int, user_id: int) -> list[aiosqlite.Row]:
        return await db.fetchall(
            "SELECT * FROM expenses WHERE period_id = ? AND payer_id = ? AND deleted = 0 "
            "ORDER BY date, id", (period_id, user_id))

    @staticmethod
    async def update_field(db: Database, expense_id: int, field: str,
                           value, editor_id: int) -> None:
        assert field in {"amount", "type", "date", "payer_id", "description"}
        await db.execute(
            f"UPDATE expenses SET {field} = ?, updated_at = ?, edited_by = ? WHERE id = ?",
            (value, now_iso(), editor_id, expense_id),
        )

    @staticmethod
    async def soft_delete(db: Database, expense_id: int, editor_id: int) -> None:
        await db.execute(
            "UPDATE expenses SET deleted = 1, updated_at = ?, edited_by = ? WHERE id = ?",
            (now_iso(), editor_id, expense_id),
        )


# ----------------------------- absences ------------------------------------

class AbsenceRepo:
    @staticmethod
    async def days_of_user(db: Database, period_id: int, user_id: int) -> set[str]:
        rows = await db.fetchall(
            "SELECT date FROM absences WHERE period_id = ? AND user_id = ?",
            (period_id, user_id))
        return {r["date"] for r in rows}

    @staticmethod
    async def for_period(db: Database, period_id: int) -> set[tuple[int, str]]:
        rows = await db.fetchall(
            "SELECT user_id, date FROM absences WHERE period_id = ?", (period_id,))
        return {(r["user_id"], r["date"]) for r in rows}

    @staticmethod
    async def replace_for_user(db: Database, period_id: int, user_id: int,
                               dates: set[str]) -> None:
        await db.conn.execute(
            "DELETE FROM absences WHERE period_id = ? AND user_id = ?", (period_id, user_id))
        await db.conn.executemany(
            "INSERT INTO absences (period_id, user_id, date) VALUES (?, ?, ?)",
            [(period_id, user_id, d) for d in sorted(dates)],
        )
        await db.conn.commit()


# ----------------------------- confirmations -------------------------------

class ConfirmationRepo:
    @staticmethod
    async def add(db: Database, period_id: int, user_id: int) -> None:
        await db.execute(
            "INSERT OR IGNORE INTO confirmations (period_id, user_id, confirmed_at) "
            "VALUES (?, ?, ?)", (period_id, user_id, now_iso()))

    @staticmethod
    async def user_ids(db: Database, period_id: int) -> set[int]:
        rows = await db.fetchall(
            "SELECT user_id FROM confirmations WHERE period_id = ?", (period_id,))
        return {r["user_id"] for r in rows}

    @staticmethod
    async def reset(db: Database, period_id: int) -> None:
        await db.execute("DELETE FROM confirmations WHERE period_id = ?", (period_id,))


# ----------------------------- settlements ---------------------------------

class SettlementRepo:
    @staticmethod
    async def save(db: Database, period_id: int,
                   transfers: list[tuple[int, int, int]]) -> None:
        await db.conn.execute("DELETE FROM settlements WHERE period_id = ?", (period_id,))
        await db.conn.executemany(
            "INSERT INTO settlements (period_id, from_user, to_user, amount) "
            "VALUES (?, ?, ?, ?)",
            [(period_id, f, t, a) for f, t, a in transfers],
        )
        await db.conn.commit()

    @staticmethod
    async def for_period(db: Database, period_id: int) -> list[aiosqlite.Row]:
        return await db.fetchall(
            "SELECT s.*, uf.full_name AS from_name, ut.full_name AS to_name "
            "FROM settlements s "
            "JOIN users uf ON uf.id = s.from_user "
            "JOIN users ut ON ut.id = s.to_user "
            "WHERE s.period_id = ? ORDER BY s.amount DESC", (period_id,))


# ----------------------------- scheduler_log -------------------------------

class SchedulerLogRepo:
    @staticmethod
    async def was_executed(db: Database, job_key: str) -> bool:
        row = await db.fetchone(
            "SELECT 1 FROM scheduler_log WHERE job_key = ?", (job_key,))
        return row is not None

    @staticmethod
    async def try_acquire(db: Database, job_key: str) -> bool:
        """True — ключ свободен и захвачен; False — джоб уже выполнялся."""
        try:
            await db.execute(
                "INSERT INTO scheduler_log (job_key, executed_at) VALUES (?, ?)",
                (job_key, now_iso()))
            return True
        except Exception:
            return False
