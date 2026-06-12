"""Общие клавиатуры."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BTN_ADD_EXPENSE = "➕ Добавить трату"
BTN_ABSENCES = "📅 Мои отсутствия"
BTN_MY_EXPENSES = "📋 Мои траты"
BTN_CALC = "📊 Расчёт"
BTN_ADMIN = "⚙️ Админ-панель"
BTN_CANCEL = "❌ Отмена"


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_ADD_EXPENSE), KeyboardButton(text=BTN_ABSENCES)],
        [KeyboardButton(text=BTN_MY_EXPENSES), KeyboardButton(text=BTN_CALC)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")],
    ])


def expense_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Общая — платят все", callback_data="exp_type:common")],
        [InlineKeyboardButton(text="📆 Дневная — платят присутствовавшие",
                              callback_data="exp_type:daily")],
        [InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")],
    ])


def skip_or_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="exp_desc:skip")],
        [InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")],
    ])


def expense_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="exp:save")],
        [InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")],
    ])


def absence_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="abs:save")],
        [InlineKeyboardButton(text="◀️ Назад к календарю", callback_data="abs:back")],
        [InlineKeyboardButton(text=BTN_CANCEL, callback_data="fsm:cancel")],
    ])


def confirm_calc_kb(period_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить расчёт",
                              callback_data=f"confirm:{period_id}")],
    ])


def users_kb(users, prefix: str, back_cb: str | None = None) -> InlineKeyboardMarkup:
    """Список участников кнопками: callback_data = f'{prefix}:{user_id}'."""
    b = InlineKeyboardBuilder()
    for u in users:
        b.row(InlineKeyboardButton(text=u["full_name"], callback_data=f"{prefix}:{u['id']}"))
    if back_cb:
        b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=back_cb))
    return b.as_markup()
