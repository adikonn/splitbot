"""Тесты хэндлеров участника: AddExpenseFSM, AbsenceFSM, расчёт и подтверждение."""
from db.repositories import (
    AbsenceRepo,
    ConfirmationRepo,
    ExpenseRepo,
    PeriodRepo,
    UserRepo,
)
from handlers.member.absences import (
    abs_done,
    abs_save,
    abs_toggle,
    absences_start,
)
from handlers.member.confirm import calc_status, confirm_calc
from handlers.member.expenses import (
    add_expense_start,
    choose_type,
    enter_amount,
    enter_description,
    my_expenses,
    save_expense,
    skip_description,
)
from states.states import AbsenceFSM, AddExpenseFSM
from tests.conftest import BOB_TG
from tests.helpers import answered_text, edited_text, fake_callback, fake_message


# --------------------------- AddExpenseFSM ----------------------------------

async def test_add_expense_full_flow(db, seeded, state):
    bob = await UserRepo.get(db, seeded["bob"])

    msg = fake_message("➕ Добавить трату", user_id=BOB_TG)
    await add_expense_start(msg, state, db)
    assert await state.get_state() == AddExpenseFSM.choosing_type
    assert (await state.get_data())["period_id"] == seeded["period"]

    cb = fake_callback("exp_type:daily", user_id=BOB_TG)
    await choose_type(cb, state)
    assert await state.get_state() == AddExpenseFSM.choosing_date
    assert (await state.get_data())["type"] == "daily"
    # календарь приложен к сообщению
    assert cb.message.edit_text.await_args.kwargs["reply_markup"] is not None

    # шаг календаря — фиксируем дату напрямую (aiogram_calendar — внешний код)
    await state.update_data(date="2026-06-05")
    await state.set_state(AddExpenseFSM.entering_amount)

    bad = fake_message("сто рублей", user_id=BOB_TG)
    await enter_amount(bad, state)
    assert await state.get_state() == AddExpenseFSM.entering_amount  # не пустил

    ok = fake_message("99,90", user_id=BOB_TG)
    await enter_amount(ok, state)
    assert await state.get_state() == AddExpenseFSM.entering_description
    assert (await state.get_data())["amount"] == 9990

    descr = fake_message("такси", user_id=BOB_TG)
    await enter_description(descr, state)
    assert await state.get_state() == AddExpenseFSM.confirming
    card = answered_text(descr)
    assert "99.90" in card and "такси" in card and "05.06.2026" in card

    save_cb = fake_callback("exp:save", user_id=BOB_TG)
    await save_expense(save_cb, state, db, bob)
    assert await state.get_state() is None

    rows = await ExpenseRepo.for_user(db, seeded["period"], seeded["bob"])
    assert len(rows) == 1
    e = rows[0]
    assert (e["type"], e["date"], e["amount"], e["description"]) == \
        ("daily", "2026-06-05", 9990, "такси")


async def test_skip_description(db, seeded, state):
    await state.set_state(AddExpenseFSM.entering_description)
    await state.update_data(period_id=seeded["period"], type="common",
                            date="2026-06-01", amount=100)
    cb = fake_callback("exp_desc:skip", user_id=BOB_TG)
    await skip_description(cb, state)
    assert await state.get_state() == AddExpenseFSM.confirming
    assert (await state.get_data())["description"] == ""


async def test_my_expenses_empty_and_filled(db, seeded, state):
    bob = await UserRepo.get(db, seeded["bob"])
    msg = fake_message("📋 Мои траты", user_id=BOB_TG)
    await my_expenses(msg, db, bob)
    assert "нет трат" in answered_text(msg)

    await ExpenseRepo.add(db, seeded["period"], seeded["bob"],
                          "common", "2026-06-01", 150_00, "продукты")
    msg2 = fake_message("📋 Мои траты", user_id=BOB_TG)
    await my_expenses(msg2, db, bob)
    text = answered_text(msg2)
    assert "150.00" in text and "продукты" in text and "Итого" in text


# --------------------------- AbsenceFSM -------------------------------------

async def test_absence_full_flow(db, seeded, state):
    bob = await UserRepo.get(db, seeded["bob"])
    await AbsenceRepo.replace_for_user(db, seeded["period"], seeded["bob"],
                                       {"2026-06-03"})  # уже отмеченный день

    msg = fake_message("📅 Мои отсутствия", user_id=BOB_TG)
    await absences_start(msg, state, db, bob)
    assert await state.get_state() == AbsenceFSM.picking_dates
    assert (await state.get_data())["selected"] == [3]   # подтянулось из БД

    await abs_toggle(fake_callback("abs:toggle:5"), state)
    await abs_toggle(fake_callback("abs:toggle:6"), state)
    await abs_toggle(fake_callback("abs:toggle:5"), state)  # снял обратно
    assert (await state.get_data())["selected"] == [3, 6]

    done = fake_callback("abs:done")
    await abs_done(done, state)
    assert await state.get_state() == AbsenceFSM.confirming
    assert "3, 6" in edited_text(done)

    save = fake_callback("abs:save")
    await abs_save(save, state, db, bob)
    assert await state.get_state() is None
    assert await AbsenceRepo.days_of_user(db, seeded["period"], seeded["bob"]) == \
        {"2026-06-03", "2026-06-06"}


async def test_absence_save_empty_clears(db, seeded, state):
    bob = await UserRepo.get(db, seeded["bob"])
    await AbsenceRepo.replace_for_user(db, seeded["period"], seeded["bob"],
                                       {"2026-06-03"})
    await state.set_state(AbsenceFSM.confirming)
    await state.update_data(period_id=seeded["period"], year=2026, month=6,
                            selected=[])
    await abs_save(fake_callback("abs:save"), state, db, bob)
    assert await AbsenceRepo.days_of_user(db, seeded["period"], seeded["bob"]) == set()


# --------------------------- расчёт и подтверждение -------------------------

async def test_calc_status_open_period(db, seeded, bot):
    bob = await UserRepo.get(db, seeded["bob"])
    msg = fake_message("📊 Расчёт", user_id=BOB_TG)
    await calc_status(msg, db, bob)
    assert "открыт" in answered_text(msg)


async def test_calc_status_confirming_shows_button(db, seeded, bot):
    await PeriodRepo.to_confirming(db, seeded["period"])
    bob = await UserRepo.get(db, seeded["bob"])
    msg = fake_message("📊 Расчёт", user_id=BOB_TG)
    await calc_status(msg, db, bob)
    assert msg.answer.await_args.kwargs["reply_markup"] is not None

    await ConfirmationRepo.add(db, seeded["period"], seeded["bob"])
    msg2 = fake_message("📊 Расчёт", user_id=BOB_TG)
    await calc_status(msg2, db, bob)
    assert "уже подтвердили" in answered_text(msg2)
    assert msg2.answer.await_args.kwargs["reply_markup"] is None


async def test_confirm_calc_partial_then_close(db, seeded, bot):
    await ExpenseRepo.add(db, seeded["period"], seeded["admin"],
                          "common", "2026-06-01", 300_00, "аренда")
    await PeriodRepo.to_confirming(db, seeded["period"])
    pid = seeded["period"]

    bob = await UserRepo.get(db, seeded["bob"])
    cb = fake_callback(f"confirm:{pid}", user_id=BOB_TG)
    await confirm_calc(cb, db, bob, bot)
    assert await ConfirmationRepo.user_ids(db, pid) == {seeded["bob"]}
    assert (await PeriodRepo.get(db, pid))["status"] == "confirming"
    cb.message.edit_text.assert_awaited()        # превью обновлено

    for key in ("eva", "admin"):
        user = await UserRepo.get(db, seeded[key])
        await confirm_calc(fake_callback(f"confirm:{pid}", user_id=user["tg_id"]),
                           db, user, bot)
    assert (await PeriodRepo.get(db, pid))["status"] == "closed"
    assert any("закрыт" in t for t in bot.texts_for(BOB_TG))


async def test_confirm_calc_on_closed_period(db, seeded, bot):
    await PeriodRepo.to_confirming(db, seeded["period"])
    await PeriodRepo.to_closed(db, seeded["period"])
    bob = await UserRepo.get(db, seeded["bob"])
    cb = fake_callback(f"confirm:{seeded['period']}", user_id=BOB_TG)
    await confirm_calc(cb, db, bob, bot)
    assert "уже закрыт" in cb.answer.await_args.args[0]
    assert await ConfirmationRepo.user_ids(db, seeded["period"]) == set()
