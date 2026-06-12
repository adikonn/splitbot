"""Финальные ветки: пагинация списка трат, навигация календаря без выбора,
невалидная сумма при правке, карточка с аудитом, remove_confirm для missing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db.repositories import ExpenseRepo, UserRepo
from handlers.admin.expenses import edit_amount, expense_card, list_expenses
from handlers.admin.members import remove_confirm
from handlers.member.expenses import choose_date
from states.states import AddExpenseFSM, EditExpenseFSM
from tests.conftest import ADMIN_TG, BOB_TG
from tests.helpers import edited_text, fake_callback, fake_message


def _no_selection():
    """Тап по навигации календаря: selected=False, дата отсутствует."""
    return patch("aiogram_calendar.SimpleCalendar.process_selection",
                 new=AsyncMock(return_value=(False, None)))


async def test_expenses_pagination(db, seeded, state):
    for i in range(1, 12):                                  # 11 трат, PAGE=8 → 2 стр.
        await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                              "common", f"2026-06-{i:02d}", i * 100, "")
    cb0 = fake_callback("adm:expenses:0", user_id=ADMIN_TG)
    await list_expenses(cb0, state, db)
    kb0 = cb0.message.edit_text.await_args.kwargs["reply_markup"]
    datas0 = [b.callback_data for row in kb0.inline_keyboard for b in row]
    assert "adm:expenses:1" in datas0 and "adm:expenses:-1" not in datas0
    assert "стр. 1/2" in edited_text(cb0)

    cb1 = fake_callback("adm:expenses:1", user_id=ADMIN_TG)
    await list_expenses(cb1, state, db)
    kb1 = cb1.message.edit_text.await_args.kwargs["reply_markup"]
    datas1 = [b.callback_data for row in kb1.inline_keyboard for b in row]
    assert "adm:expenses:0" in datas1                       # стрелка назад
    assert "стр. 2/2" in edited_text(cb1)

    cb_far = fake_callback("adm:expenses:99", user_id=ADMIN_TG)   # клампинг
    await list_expenses(cb_far, state, db)
    assert "стр. 2/2" in edited_text(cb_far)


async def test_choose_date_navigation_click(db, seeded, state):
    await state.set_state(AddExpenseFSM.choosing_date)
    await state.update_data(period_id=seeded["period"], year=2026, month=6,
                            type="common")
    cb = fake_callback(user_id=BOB_TG)
    with _no_selection():
        await choose_date(cb, SimpleNamespace(), state)
    assert await state.get_state() == AddExpenseFSM.choosing_date   # ничего не произошло
    cb.message.answer.assert_not_awaited()


async def test_admin_edit_date_navigation_click(db, seeded, state, bot):
    from handlers.admin.expenses import edit_date
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100, "")
    await state.set_state(EditExpenseFSM.editing_date)
    await state.update_data(expense_id=eid, year=2026, month=6)
    with _no_selection():
        await edit_date(fake_callback(user_id=ADMIN_TG), SimpleNamespace(),
                        state, db, admin, bot)
    assert (await ExpenseRepo.get(db, eid))["date"] == "2026-06-01"


async def test_edit_amount_invalid_keeps_state(db, seeded, state, bot):
    admin = await UserRepo.get(db, seeded["admin"])
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100_00, "")
    await state.set_state(EditExpenseFSM.editing_amount)
    await state.update_data(expense_id=eid)
    msg = fake_message("много", user_id=ADMIN_TG)
    await edit_amount(msg, state, db, admin, bot)
    assert await state.get_state() == EditExpenseFSM.editing_amount
    assert (await ExpenseRepo.get(db, eid))["amount"] == 100_00


async def test_expense_card_shows_audit_and_missing(db, seeded, state):
    eid = await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                                "common", "2026-06-01", 100_00, "")
    await ExpenseRepo.update_field(db, eid, "amount", 200_00, seeded["admin"])
    cb = fake_callback(f"adm:exp:{eid}", user_id=ADMIN_TG)
    await expense_card(cb, state, db)
    assert "правил(а): Админ" in edited_text(cb)

    await ExpenseRepo.soft_delete(db, eid, seeded["admin"])
    gone = fake_callback(f"adm:exp:{eid}", user_id=ADMIN_TG)
    await expense_card(gone, state, db)
    assert "не найдена" in gone.answer.await_args.args[0]


async def test_remove_confirm_missing_user(db, seeded):
    cb = fake_callback("adm:rm:9999", user_id=ADMIN_TG)
    await remove_confirm(cb, db)
    assert "Не найден" in cb.answer.await_args.args[0]
