"""Тесты handlers/start.py: /start, JoinFSM, отмена."""
from db.repositories import UserRepo
from handlers.start import cb_cancel, cmd_start, join_name, msg_cancel
from states.states import AddExpenseFSM, JoinFSM
from tests.conftest import ADMIN_TG, BOB_TG
from tests.helpers import answered_text, fake_callback, fake_message


async def test_start_active_user_gets_menu(db, seeded, state, config):
    msg = fake_message("/start", user_id=BOB_TG)
    await cmd_start(msg, state, db, config)
    assert "Боб" in answered_text(msg)
    assert msg.answer.await_args.kwargs["reply_markup"] is not None
    assert await state.get_state() is None


async def test_start_pending_user(db, seeded, state, config):
    await UserRepo.set_status(db, seeded["bob"], "pending")
    msg = fake_message("/start", user_id=BOB_TG)
    await cmd_start(msg, state, db, config)
    assert "на рассмотрении" in answered_text(msg)
    assert await state.get_state() is None


async def test_start_new_user_enters_join_fsm(db, state, config):
    msg = fake_message("/start", user_id=777)
    await cmd_start(msg, state, db, config)
    assert await state.get_state() == JoinFSM.waiting_name
    assert "заявку" in answered_text(msg)


async def test_join_name_too_short(db, state, config, bot):
    await state.set_state(JoinFSM.waiting_name)
    msg = fake_message("Я", user_id=777)
    await join_name(msg, state, db, config, bot)
    assert await state.get_state() == JoinFSM.waiting_name   # остаёмся в состоянии
    assert await UserRepo.get_by_tg(db, 777) is None


async def test_join_name_creates_request_and_notifies_admin(db, state, config, bot):
    await state.set_state(JoinFSM.waiting_name)
    msg = fake_message("Новичок", user_id=777, username="newbie")
    await join_name(msg, state, db, config, bot)
    user = await UserRepo.get_by_tg(db, 777)
    assert user["status"] == "pending" and user["full_name"] == "Новичок"
    assert any("Новичок" in t for t in bot.texts_for(ADMIN_TG))
    assert "отправлена администратору" in answered_text(msg)
    assert await state.get_state() is None


async def test_admin_first_start_self_registers(db, state, config, bot):
    msg = fake_message("/start", user_id=ADMIN_TG)
    await cmd_start(msg, state, db, config)
    assert await state.get_state() == JoinFSM.waiting_name

    msg2 = fake_message("Главный", user_id=ADMIN_TG)
    await join_name(msg2, state, db, config, bot)
    user = await UserRepo.get_by_tg(db, ADMIN_TG)
    assert user["role"] == "admin" and user["status"] == "active"
    assert bot.sent == []                                   # заявка админу не шлётся


async def test_cancel_callback_clears_state(db, state):
    await state.set_state(AddExpenseFSM.entering_amount)
    cb = fake_callback("fsm:cancel")
    await cb_cancel(cb, state)
    assert await state.get_state() is None
    cb.message.edit_text.assert_awaited_once()


async def test_cancel_message_clears_state(db, state):
    await state.set_state(AddExpenseFSM.entering_amount)
    msg = fake_message("/cancel")
    await msg_cancel(msg, state)
    assert await state.get_state() is None
