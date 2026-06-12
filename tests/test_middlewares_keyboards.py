"""Тесты middleware (контроль доступа) и клавиатур/календарей."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db.repositories import UserRepo
from keyboards.calendar import in_period, multiselect_month_kb
from keyboards.common import expense_type_kb, main_menu, users_kb
from middlewares.access import AccessMiddleware, AdminMiddleware
from tests.conftest import ADMIN_TG, BOB_TG


# ----------------------------- AccessMiddleware -----------------------------

async def _run_access(db, tg_id):
    mw = AccessMiddleware(db)
    handler = AsyncMock(return_value="handled")
    data = {"event_from_user": SimpleNamespace(id=tg_id)}
    with patch("middlewares.access._deny", new=AsyncMock()) as deny:
        result = await mw(handler, object(), data)
    return result, handler, data, deny


async def test_access_active_user_passes(db, seeded):
    result, handler, data, deny = await _run_access(db, BOB_TG)
    assert result == "handled" and handler.await_count == 1
    assert data["db_user"]["full_name"] == "Боб"
    assert data["db"] is db
    assert deny.await_count == 0


async def test_access_unknown_denied(db, seeded):
    result, handler, _, deny = await _run_access(db, 9999)
    assert result is None and handler.await_count == 0
    assert "/start" in deny.await_args.args[1]


async def test_access_pending_denied(db, seeded):
    await UserRepo.set_status(db, seeded["bob"], "pending")
    result, handler, _, deny = await _run_access(db, BOB_TG)
    assert result is None and handler.await_count == 0
    assert "рассмотрении" in deny.await_args.args[1]


async def test_access_removed_denied(db, seeded):
    await UserRepo.set_status(db, seeded["bob"], "removed")
    result, handler, _, _ = await _run_access(db, BOB_TG)
    assert result is None and handler.await_count == 0


# ----------------------------- AdminMiddleware ------------------------------

async def _run_admin(db, user_row):
    mw = AdminMiddleware()
    handler = AsyncMock(return_value="handled")
    with patch("middlewares.access._deny", new=AsyncMock()) as deny:
        result = await mw(handler, object(), {"db_user": user_row})
    return result, handler, deny


async def test_admin_mw_allows_admin(db, seeded):
    admin = await UserRepo.get(db, seeded["admin"])
    result, handler, _ = await _run_admin(db, admin)
    assert result == "handled" and handler.await_count == 1


async def test_admin_mw_blocks_member(db, seeded):
    bob = await UserRepo.get(db, seeded["bob"])
    result, handler, deny = await _run_admin(db, bob)
    assert result is None and handler.await_count == 0
    assert "администратору" in deny.await_args.args[1]


# ----------------------------- клавиатуры -----------------------------------

def test_main_menu_admin_row():
    member = main_menu(is_admin=False)
    admin = main_menu(is_admin=True)
    assert len(member.keyboard) == 2
    assert len(admin.keyboard) == 3
    assert admin.keyboard[2][0].text == "⚙️ Админ-панель"


def test_expense_type_callbacks():
    kb = expense_type_kb()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "exp_type:common" in datas and "exp_type:daily" in datas


def test_users_kb_prefix(db):
    users = [{"id": 1, "full_name": "А"}, {"id": 2, "full_name": "Б"}]
    kb = users_kb(users, "setpayer", back_cb="adm:back")
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["setpayer:1", "setpayer:2", "adm:back"]


def test_multiselect_grid_june_2026():
    kb = multiselect_month_kb(2026, 6, selected={5, 30})
    flat = [b for row in kb.inline_keyboard for b in row]
    texts = [b.text for b in flat]
    assert texts[:7] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    assert "✅5" in texts and "✅30" in texts and "6" in texts
    assert "31" not in texts and "✅31" not in texts      # в июне 30 дней
    datas = [b.callback_data for b in flat]
    assert "abs:toggle:5" in datas and "abs:done" in datas and "abs:clear" in datas


def test_in_period():
    from datetime import date
    assert in_period(date(2026, 6, 15), 2026, 6)
    assert not in_period(date(2026, 7, 1), 2026, 6)
    assert not in_period(date(2025, 6, 15), 2026, 6)
