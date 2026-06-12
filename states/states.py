"""Все StatesGroup проекта."""
from aiogram.fsm.state import State, StatesGroup


class JoinFSM(StatesGroup):
    waiting_name = State()


class AddExpenseFSM(StatesGroup):
    choosing_type = State()
    choosing_date = State()
    entering_amount = State()
    entering_description = State()
    confirming = State()


class AbsenceFSM(StatesGroup):
    picking_dates = State()
    confirming = State()


class EditExpenseFSM(StatesGroup):
    choosing_action = State()
    editing_amount = State()
    editing_type = State()
    editing_date = State()
    editing_payer = State()
    editing_description = State()
    confirming_delete = State()
