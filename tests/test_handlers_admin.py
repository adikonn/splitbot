"""Тесты админских хэндлеров: панель, заявки, исключение, правка трат, период."""
from db.repositories import (
    ConfirmationRepo,
    ExpenseRepo,
    PeriodRepo,
    SettlementRepo,
    UserRepo,
)
from handlers.admin.expenses import (
    choose_action,
    delete_expense,
    edit_amount,
    expense_card,
    list_expenses,
)
from handlers.admin.members import (
    approve_request,
    list_members,
    reject_request,
    remove_confirm,
    remove_do,
)
from handlers.admin.panel import admin_panel, panel_kb
from handlers.admin.period import force_close_do, manual_settle, period_menu
from services.membership import submit_request
from states.states import EditExpenseFSM
from tests.conftest import ADMIN_TG, BOB_TG
from tests.helpers import answered_text, edited_text, fake_callback, fake_message


# ------------------------------- панель -------------------------------------

async def test_panel_badge_counts_pending(db, seeded, bot):
    kb = await panel_kb(db)
    assert kb.inline_keyboard[0][0].text == "📨 Заявки"
    await submit_request(bot, db, ADMIN_TG, 777, None, "Новичок")
    kb = await panel_kb(db)
    assert kb.inline_keyboard[0][0].text == "📨 Заявки (1)"


async def test_panel_shows_period_status(db, seeded):
    msg = fake_message("⚙️ Админ-панель", user_id=ADMIN_TG)
    await admin_panel(msg, db)
    assert "июнь 2026 — открыт" in answered_text(msg)


# ------------------------------- заявки -------------------------------------

async def test_approve_reject_callbacks(db, bot):
    await submit_request(bot, db, ADMIN_TG, 777, None, "Новичок")
    await submit_request(bot, db, ADMIN_TG, 888, None, "Второй")
    u1 = await UserRepo.get_by_tg(db, 777)
    u2 = await UserRepo.get_by_tg(db, 888)

    cb = fake_callback(f"req:approve:{u1['id']}", user_id=ADMIN_TG)
    await approve_request(cb, db, bot)
    assert "принят" in edited_text(cb)
    assert (await UserRepo.get(db, u1["id"]))["status"] == "active"

    cb2 = fake_callback(f"req:reject:{u2['id']}", user_id=ADMIN_TG)
    await reject_request(cb2, db, bot)
    assert (await UserRepo.get(db, u2["id"]))["status"] == "removed"


# ------------------------------- состав -------------------------------------

async def test_members_list_and_remove(db, seeded, bot):
    cb = fake_callback("adm:members", user_id=ADMIN_TG)
    await list_members(cb, db)
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "👑 Админ" in texts and "Боб" in texts

    ask = fake_callback(f"adm:rm:{seeded['bob']}", user_id=ADMIN_TG)
    await remove_confirm(ask, db)
    assert "Исключить" in edited_text(ask)

    do = fake_callback(f"adm:rmyes:{seeded['bob']}", user_id=ADMIN_TG)
    await remove_do(do, db, bot)
    assert (await UserRepo.get(db, seeded["bob"]))["status"] == "removed"


# ------------------------------- траты --------------------------------------

async def test_list_expenses_empty_alert(db, seeded, state):
    cb = fake_callback("adm:expenses:0", user_id=ADMIN_TG)
    await list_expenses(cb, state, db)
    assert "Трат пока нет" in cb.answer.await_args.args[0]


async def test_expense_card_and_edit_amount(db, seeded, state, bot):
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100_00, "продукты")

    cb_list = fake_callback("adm:expenses:0", user_id=ADMIN_TG)
    await list_expenses(cb_list, state, db)
    kb = cb_list.message.edit_text.await_args.kwargs["reply_markup"]
    assert any(b.callback_data == f"adm:exp:{eid}"
               for row in kb.inline_keyboard for b in row)

    cb_card = fake_callback(f"adm:exp:{eid}", user_id=ADMIN_TG)
    await expense_card(cb_card, state, db)
    assert await state.get_state() == EditExpenseFSM.choosing_action
    assert "100.00" in edited_text(cb_card)

    cb_edit = fake_callback(f"adm:exp:{eid}:amount", user_id=ADMIN_TG)
    await choose_action(cb_edit, state, db)
    assert await state.get_state() == EditExpenseFSM.editing_amount

    msg = fake_message("250", user_id=ADMIN_TG)
    await edit_amount(msg, state, db, admin, bot)
    e = await ExpenseRepo.get(db, eid)
    assert e["amount"] == 250_00 and e["edited_by"] == seeded["admin"]
    assert await state.get_state() == EditExpenseFSM.choosing_action
    assert "250.00" in answered_text(msg)             # карточка показана заново
    assert bot.sent == []                             # период open — рассылки нет


async def test_edit_in_confirming_resets_confirmations(db, seeded, state, bot):
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100_00, "")
    await PeriodRepo.to_confirming(db, seeded["period"])
    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])

    await state.set_state(EditExpenseFSM.editing_amount)
    await state.update_data(expense_id=eid)
    await edit_amount(fake_message("300", user_id=ADMIN_TG), state, db, admin, bot)

    assert await ConfirmationRepo.user_ids(db, seeded["period"]) == set()
    assert any("подтверждения сброшены" in t for t in bot.texts_for(BOB_TG))


async def test_delete_expense(db, seeded, state, bot):
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100_00, "")
    await state.set_state(EditExpenseFSM.confirming_delete)
    await state.update_data(expense_id=eid)
    cb = fake_callback("expdel:yes", user_id=ADMIN_TG)
    await delete_expense(cb, state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["deleted"] == 1
    assert await state.get_state() is None
    assert "удалена" in edited_text(cb)


# ------------------------------- период -------------------------------------

async def test_period_menu_buttons(db, seeded):
    cb = fake_callback("adm:period", user_id=ADMIN_TG)
    await period_menu(cb, db)
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "adm:settle" in datas and "adm:forceclose" not in datas

    await PeriodRepo.to_confirming(db, seeded["period"])
    cb2 = fake_callback("adm:period", user_id=ADMIN_TG)
    await period_menu(cb2, db)
    datas = [b.callback_data for row in cb2.message.edit_text.await_args
             .kwargs["reply_markup"].inline_keyboard for b in row]
    assert "adm:forceclose" in datas


async def test_manual_settle_and_force_close(db, seeded, bot):
    cb = fake_callback("adm:settle", user_id=ADMIN_TG)
    await manual_settle(cb, db, bot)
    assert (await PeriodRepo.get(db, seeded["period"]))["status"] == "confirming"
    assert "запущен" in cb.answer.await_args.args[0]

    # повторный запуск запрещён, пока июнь не закрыт
    cb_again = fake_callback("adm:settle", user_id=ADMIN_TG)
    await manual_settle(cb_again, db, bot)
    assert "Нельзя" in cb_again.answer.await_args.args[0]

    cb_close = fake_callback("adm:forceclose:yes", user_id=ADMIN_TG)
    await force_close_do(cb_close, db, bot)
    period = await PeriodRepo.get(db, seeded["period"])
    assert period["status"] == "closed"
    assert await SettlementRepo.for_period(db, seeded["period"]) is not None
