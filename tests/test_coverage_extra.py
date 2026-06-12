"""Дополнительное покрытие: config, build_dispatcher, шаги календаря (через патч
process_selection), ветки админских хэндлеров, _deny, notifications, утилиты."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Message

from config import load_config
from db.repositories import AbsenceRepo, ExpenseRepo, UserRepo
from handlers.admin.expenses import (
    choose_action,
    edit_date,
    edit_description,
    edit_payer,
    edit_type,
)
from handlers.admin.members import list_requests, member_card
from handlers.admin.panel import admin_back
from handlers.admin.period import force_close_ask, force_close_do
from handlers.member.absences import abs_back, abs_clear, abs_noop
from handlers.member.confirm import calc_status
from handlers.member.expenses import choose_date
from main import build_dispatcher
from middlewares.access import AccessMiddleware, _deny
from services import period_service
from services.calculation import ExpenseItem, compute_balances
from services.membership import submit_request
from services.notifications import broadcast
from states.states import AbsenceFSM, AddExpenseFSM, EditExpenseFSM
from tests.conftest import ADMIN_TG, BOB_TG
from tests.helpers import edited_text, fake_callback, fake_message
from utils import user_label


# ------------------------------- config -------------------------------------

def test_load_config_ok(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "1:abc")
    monkeypatch.setenv("ADMIN_TG_ID", "42")
    monkeypatch.setenv("SETTLE_DAY", "2")
    cfg = load_config()
    assert cfg.bot_token == "1:abc" and cfg.admin_tg_id == 42 and cfg.settle_day == 2


def test_load_config_missing_token(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("ADMIN_TG_ID", "42")
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        load_config()


def test_load_config_bad_admin(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "1:abc")
    monkeypatch.setenv("ADMIN_TG_ID", "не число")
    with pytest.raises(RuntimeError, match="ADMIN_TG_ID"):
        load_config()


# ------------------------------- main ----------------------------------------

def test_build_dispatcher_wiring(db, config):
    dp = build_dispatcher(db, config)
    assert dp["db"] is db and dp["config"] is config
    names = {r.name for r in dp.sub_routers}
    assert names == {"start", "admin", "member"}
    # порядок: незащищённый start первым, админ раньше участника
    assert [r.name for r in dp.sub_routers] == ["start", "admin", "member"]


# --------------------------- _deny с реальными типами ------------------------

async def test_deny_message_and_callback():
    msg = AsyncMock(spec=Message)
    msg.answer = AsyncMock()
    await _deny(msg, "нет доступа")
    msg.answer.assert_awaited_once_with("нет доступа")

    cb = AsyncMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    await _deny(cb, "нет доступа")
    cb.answer.assert_awaited_once_with("нет доступа", show_alert=True)


async def test_access_skips_event_without_user(db):
    mw = AccessMiddleware(db)
    handler = AsyncMock()
    assert await mw(handler, object(), {}) is None
    handler.assert_not_awaited()


# --------------------------- шаг календаря (участник) ------------------------

def _patched_selection(result_date):
    """Подменяет SimpleCalendar.process_selection детерминированным результатом."""
    return patch(
        "aiogram_calendar.SimpleCalendar.process_selection",
        new=AsyncMock(return_value=(True, datetime.combine(
            result_date, datetime.min.time()))),
    )


async def test_choose_date_in_period(db, seeded, state):
    from datetime import date
    await state.set_state(AddExpenseFSM.choosing_date)
    await state.update_data(period_id=seeded["period"], year=2026, month=6,
                            type="common")
    cb = fake_callback(user_id=BOB_TG)
    with _patched_selection(date(2026, 6, 10)):
        await choose_date(cb, SimpleNamespace(), state)
    assert await state.get_state() == AddExpenseFSM.entering_amount
    assert (await state.get_data())["date"] == "2026-06-10"


async def test_choose_date_out_of_period_rejected(db, seeded, state):
    from datetime import date
    await state.set_state(AddExpenseFSM.choosing_date)
    await state.update_data(period_id=seeded["period"], year=2026, month=6,
                            type="common")
    cb = fake_callback(user_id=BOB_TG)
    with _patched_selection(date(2026, 7, 1)):
        await choose_date(cb, SimpleNamespace(), state)
    assert await state.get_state() == AddExpenseFSM.choosing_date   # остаёмся
    assert "вне расчётного месяца" in cb.message.answer.await_args.args[0]


# --------------------------- абсенсы: noop/clear/back ------------------------

async def test_abs_noop_clear_back(db, seeded, state):
    await state.set_state(AbsenceFSM.picking_dates)
    await state.update_data(period_id=seeded["period"], year=2026, month=6,
                            selected=[3, 7])
    await abs_noop(fake_callback("abs:noop"))

    cb = fake_callback("abs:clear")
    await abs_clear(cb, state)
    assert (await state.get_data())["selected"] == []

    await state.set_state(AbsenceFSM.confirming)
    back = fake_callback("abs:back")
    await abs_back(back, state)
    assert await state.get_state() == AbsenceFSM.picking_dates
    back.message.edit_text.assert_awaited_once()


# --------------------------- calc_status: прошлый итог ------------------------

async def test_calc_status_shows_last_closed(db, seeded, bot):
    await ExpenseRepo.add(db, seeded["period"], seeded["admin"],
                          "common", "2026-06-01", 300_00, "аренда")
    from db.repositories import ConfirmationRepo, PeriodRepo
    await PeriodRepo.to_confirming(db, seeded["period"])
    await period_service.close_period(bot, db, seeded["period"], forced=True)

    bob = await UserRepo.get(db, seeded["bob"])
    msg = fake_message("📊 Расчёт", user_id=BOB_TG)
    await calc_status(msg, db, bob)
    text = msg.answer.await_args.args[0]
    assert "Последний закрытый расчёт" in text and "июнь 2026" in text


# --------------------------- админ: заявки и карточка -------------------------

async def test_list_requests_empty_alert(db, seeded):
    cb = fake_callback("adm:requests", user_id=ADMIN_TG)
    await list_requests(cb, db)
    assert "Новых заявок нет" in cb.answer.await_args.args[0]


async def test_list_requests_with_pending(db, seeded, bot):
    await submit_request(bot, db, ADMIN_TG, 777, "newbie", "Новичок")
    cb = fake_callback("adm:requests", user_id=ADMIN_TG)
    await list_requests(cb, db)
    sent = cb.message.answer.await_args.args[0]
    assert "Новичок" in sent


async def test_member_card_and_missing(db, seeded):
    cb = fake_callback(f"adm:member:{seeded['bob']}", user_id=ADMIN_TG)
    await member_card(cb, db)
    text = edited_text(cb)
    assert "Боб" in text and "@bob" in text
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"adm:rm:{seeded['bob']}" in datas

    admin_cb = fake_callback(f"adm:member:{seeded['admin']}", user_id=ADMIN_TG)
    await member_card(admin_cb, db)             # у админа нет кнопки удаления
    kb = admin_cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert all(not b.callback_data.startswith("adm:rm:")
               for row in kb.inline_keyboard for b in row)

    missing = fake_callback("adm:member:9999", user_id=ADMIN_TG)
    await member_card(missing, db)
    assert "Не найден" in missing.answer.await_args.args[0]


async def test_admin_back(db, seeded):
    cb = fake_callback("adm:back", user_id=ADMIN_TG)
    await admin_back(cb, db)
    assert "Админ-панель" in edited_text(cb)


# --------------------------- админ: остальные ветки правки --------------------

async def _expense_in_action_state(db, seeded, state, **fields):
    eid = await ExpenseRepo.add(
        db, seeded["period"], seeded["bob"], fields.get("type", "common"),
        fields.get("date", "2026-06-01"), fields.get("amount", 100_00),
        fields.get("description", ""))
    await state.set_state(EditExpenseFSM.choosing_action)
    await state.update_data(expense_id=eid)
    return eid


async def test_choose_action_all_branches(db, seeded, state):
    eid = await _expense_in_action_state(db, seeded, state)
    expected = {
        "type": EditExpenseFSM.editing_type,
        "date": EditExpenseFSM.editing_date,
        "payer": EditExpenseFSM.editing_payer,
        "descr": EditExpenseFSM.editing_description,
        "del": EditExpenseFSM.confirming_delete,
    }
    for action, st in expected.items():
        await state.set_state(EditExpenseFSM.choosing_action)
        cb = fake_callback(f"adm:exp:{eid}:{action}", user_id=ADMIN_TG)
        await choose_action(cb, state, db)
        assert await state.get_state() == st, action


async def test_edit_type_payer_description(db, seeded, state, bot):
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await _expense_in_action_state(db, seeded, state)

    await state.set_state(EditExpenseFSM.editing_type)
    await edit_type(fake_callback("settype:daily", user_id=ADMIN_TG),
                    state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["type"] == "daily"

    await state.set_state(EditExpenseFSM.editing_payer)
    await edit_payer(fake_callback(f"setpayer:{seeded['eva']}", user_id=ADMIN_TG),
                     state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["payer_id"] == seeded["eva"]

    await state.set_state(EditExpenseFSM.editing_description)
    await edit_description(fake_message("кофе", user_id=ADMIN_TG),
                           state, db, admin, bot)
    e = await ExpenseRepo.get(db, eid)
    assert e["description"] == "кофе" and e["edited_by"] == seeded["admin"]


async def test_edit_date_branches(db, seeded, state, bot):
    from datetime import date
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await _expense_in_action_state(db, seeded, state)
    await state.set_state(EditExpenseFSM.editing_date)
    await state.update_data(year=2026, month=6)

    cb = fake_callback(user_id=ADMIN_TG)
    with _patched_selection(date(2026, 7, 2)):                 # вне месяца
        await edit_date(cb, SimpleNamespace(), state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["date"] == "2026-06-01"

    cb2 = fake_callback(user_id=ADMIN_TG)
    with _patched_selection(date(2026, 6, 15)):                # ок
        await edit_date(cb2, SimpleNamespace(), state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["date"] == "2026-06-15"


# --------------------------- админ: период ------------------------------------

async def test_force_close_ask_lists_waiting(db, seeded):
    from db.repositories import PeriodRepo
    await PeriodRepo.to_confirming(db, seeded["period"])
    cb = fake_callback("adm:forceclose", user_id=ADMIN_TG)
    await force_close_ask(cb, db)
    text = edited_text(cb)
    assert "Не подтвердили" in text and "Боб" in text


async def test_force_close_without_confirming(db, seeded):
    cb = fake_callback("adm:forceclose", user_id=ADMIN_TG)
    await force_close_ask(cb, db)
    assert "Нет периода" in cb.answer.await_args.args[0]

    cb2 = fake_callback("adm:forceclose:yes", user_id=ADMIN_TG)
    await force_close_do(cb2, db, AsyncMock())
    assert "уже закрыт" in cb2.answer.await_args.args[0]


# --------------------------- мелочи -------------------------------------------

async def test_broadcast_exclude(db, seeded, bot):
    await broadcast(bot, db, "привет", exclude_tg={BOB_TG})
    assert bot.texts_for(BOB_TG) == []
    assert len(bot.sent) == 2


def test_calculation_no_participants():
    # дневная трата исключённого плательщика в день, когда все отсутствовали
    members = [2, 3]
    exps = [ExpenseItem(payer_id=1, type="daily", date="2026-06-05", amount=100)]
    absences = {(2, "2026-06-05"), (3, "2026-06-05")}
    b = compute_balances(members, exps, absences)
    assert b == {2: 0, 3: 0}


def test_user_label_fallbacks():
    assert user_label({"full_name": "Имя", "username": "u", "tg_id": 1}) == "Имя"
    assert user_label({"full_name": "", "username": "u", "tg_id": 1}) == "@u"
    assert user_label({"full_name": "", "username": None, "tg_id": 7}) == "id7"


async def test_membership_blocked_user_on_approve(db, bot):
    await submit_request(bot, db, ADMIN_TG, 555, None, "Новичок")
    user = await UserRepo.get_by_tg(db, 555)
    bot.fail_for.add(555)                     # пользователь заблокировал бота
    from services.membership import approve, reject
    result = await approve(bot, db, user["id"])
    assert "принят" in result                 # одобрение не падает
    assert (await UserRepo.get(db, user["id"]))["status"] == "active"
    assert await reject(bot, db, user["id"]) == "Заявка уже обработана."
