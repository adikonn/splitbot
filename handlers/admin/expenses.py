"""Админ: просмотр всех трат, редактирование и удаление (EditExpenseFSM).

Правка траты периода в статусе confirming сбрасывает подтверждения участников
и рассылает обновлённый расчёт (services.period_service.on_expense_changed).
"""
from __future__ import annotations

from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_calendar import SimpleCalendarCallback

from db.database import Database
from db.repositories import ExpenseRepo, PeriodRepo, UserRepo
from keyboards.calendar import bounded_simple_calendar, in_period, start_bounded_calendar
from keyboards.common import cancel_kb, users_kb
from services.period_service import on_expense_changed
from states.states import EditExpenseFSM
from utils import fmt_date, fmt_money, parse_money, period_title

router = Router(name="admin_expenses")

PAGE = 8
TYPE_SHORT = {"common": "👥 общая", "daily": "📆 дневная"}


async def _relevant_periods(db: Database):
    out = []
    for status in ("confirming", "open"):
        p = await PeriodRepo.by_status(db, status)
        if p:
            out.append(p)
    return out


# --------------------------- список трат ------------------------------------

@router.callback_query(F.data.startswith("adm:expenses:"))
async def list_expenses(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    page = int(callback.data.split(":")[2])
    items = []
    for p in await _relevant_periods(db):
        for e in await ExpenseRepo.for_period(db, p["id"]):
            items.append((p, e))
    if not items:
        await callback.answer("Трат пока нет.", show_alert=True)
        return

    pages = (len(items) - 1) // PAGE
    page = max(0, min(page, pages))
    chunk = items[page * PAGE:(page + 1) * PAGE]

    rows = [[InlineKeyboardButton(
        text=f"{fmt_date(e['date'])} · {fmt_money(e['amount'])} · {e['payer_name']}",
        callback_data=f"adm:exp:{e['id']}")] for _, e in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:expenses:{page - 1}"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:expenses:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")])
    await callback.message.edit_text(
        f"🧾 Траты открытого и подтверждаемого периодов "
        f"(стр. {page + 1}/{pages + 1}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


# --------------------------- карточка траты ---------------------------------

async def _expense_card(db: Database, expense_id: int) -> tuple[str, InlineKeyboardMarkup]:
    e = await ExpenseRepo.get(db, expense_id)
    p = await PeriodRepo.get(db, e["period_id"])
    edited = ""
    if e["edited_by"]:
        editor = await UserRepo.get(db, e["edited_by"])
        edited = f"\n✏️ правил(а): {editor['full_name']} в {e['updated_at'][:16]}"
    text = (
        f"🧾 <b>Трата #{e['id']}</b> — {period_title(p['year'], p['month'])}"
        f" ({p['status']})\n"
        f"Плательщик: {e['payer_name']}\n"
        f"Тип: {TYPE_SHORT[e['type']]}\n"
        f"Дата: {fmt_date(e['date'])}\n"
        f"Сумма: <b>{fmt_money(e['amount'])}</b>\n"
        f"Назначение: {e['description'] or '—'}{edited}"
    )
    eid = e["id"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Сумма", callback_data=f"adm:exp:{eid}:amount"),
         InlineKeyboardButton(text="🔁 Тип", callback_data=f"adm:exp:{eid}:type")],
        [InlineKeyboardButton(text="📅 Дата", callback_data=f"adm:exp:{eid}:date"),
         InlineKeyboardButton(text="👤 Плательщик", callback_data=f"adm:exp:{eid}:payer")],
        [InlineKeyboardButton(text="📝 Назначение", callback_data=f"adm:exp:{eid}:descr"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:exp:{eid}:del")],
        [InlineKeyboardButton(text="◀️ К списку", callback_data="adm:expenses:0")],
    ])
    return text, kb


async def _back_to_card(message: Message, state: FSMContext, db: Database,
                        expense_id: int) -> None:
    await state.set_state(EditExpenseFSM.choosing_action)
    await state.update_data(expense_id=expense_id)
    text, kb = await _expense_card(db, expense_id)
    await message.answer(text, reply_markup=kb)


async def _after_edit(bot: Bot, db: Database, expense_id: int, editor) -> None:
    e = await ExpenseRepo.get(db, expense_id)
    await on_expense_changed(bot, db, e["period_id"], editor["full_name"])


@router.callback_query(F.data.regexp(r"^adm:exp:\d+$"))
async def expense_card(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    expense_id = int(callback.data.split(":")[2])
    e = await ExpenseRepo.get(db, expense_id)
    if not e or e["deleted"]:
        await callback.answer("Трата не найдена.", show_alert=True)
        return
    await state.set_state(EditExpenseFSM.choosing_action)
    await state.update_data(expense_id=expense_id)
    text, kb = await _expense_card(db, expense_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# --------------------------- ветки редактирования ---------------------------

@router.callback_query(EditExpenseFSM.choosing_action, F.data.regexp(r"^adm:exp:\d+:\w+$"))
async def choose_action(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, _, eid, action = callback.data.split(":")
    expense_id = int(eid)
    await state.update_data(expense_id=expense_id)
    e = await ExpenseRepo.get(db, expense_id)

    if action == "amount":
        await state.set_state(EditExpenseFSM.editing_amount)
        await callback.message.edit_text(
            f"Текущая сумма: {fmt_money(e['amount'])}.\nВведите новую сумму:",
            reply_markup=cancel_kb())
    elif action == "type":
        await state.set_state(EditExpenseFSM.editing_type)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Общая", callback_data="settype:common")],
            [InlineKeyboardButton(text="📆 Дневная", callback_data="settype:daily")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="fsm:cancel")],
        ])
        await callback.message.edit_text("Новый тип траты:", reply_markup=kb)
    elif action == "date":
        p = await PeriodRepo.get(db, e["period_id"])
        await state.set_state(EditExpenseFSM.editing_date)
        await state.update_data(year=p["year"], month=p["month"])
        await callback.message.edit_text(
            "Новая дата траты:",
            reply_markup=await start_bounded_calendar(p["year"], p["month"]))
    elif action == "payer":
        await state.set_state(EditExpenseFSM.editing_payer)
        await callback.message.edit_text(
            "Новый плательщик:",
            reply_markup=users_kb(await UserRepo.active(db), "setpayer",
                                  back_cb=f"adm:exp:{expense_id}"))
    elif action == "descr":
        await state.set_state(EditExpenseFSM.editing_description)
        await callback.message.edit_text("Новое назначение траты:",
                                         reply_markup=cancel_kb())
    elif action == "del":
        await state.set_state(EditExpenseFSM.confirming_delete)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Да, удалить", callback_data="expdel:yes"),
            InlineKeyboardButton(text="◀️ Нет", callback_data=f"adm:exp:{expense_id}"),
        ]])
        await callback.message.edit_text(
            f"Удалить трату #{expense_id} на {fmt_money(e['amount'])}?",
            reply_markup=kb)
    await callback.answer()


@router.message(EditExpenseFSM.editing_amount, F.text)
async def edit_amount(message: Message, state: FSMContext, db: Database,
                      db_user, bot: Bot) -> None:
    amount = parse_money(message.text)
    if amount is None:
        await message.answer("Не понял сумму, попробуйте ещё раз:", reply_markup=cancel_kb())
        return
    data = await state.get_data()
    await ExpenseRepo.update_field(db, data["expense_id"], "amount", amount, db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await _back_to_card(message, state, db, data["expense_id"])


@router.callback_query(EditExpenseFSM.editing_type, F.data.startswith("settype:"))
async def edit_type(callback: CallbackQuery, state: FSMContext, db: Database,
                    db_user, bot: Bot) -> None:
    data = await state.get_data()
    await ExpenseRepo.update_field(db, data["expense_id"], "type",
                                   callback.data.split(":")[1], db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await callback.message.delete()
    await _back_to_card(callback.message, state, db, data["expense_id"])
    await callback.answer()


@router.callback_query(EditExpenseFSM.editing_date, SimpleCalendarCallback.filter())
async def edit_date(callback: CallbackQuery, callback_data: SimpleCalendarCallback,
                    state: FSMContext, db: Database, db_user, bot: Bot) -> None:
    data = await state.get_data()
    cal = bounded_simple_calendar(data["year"], data["month"])
    selected, chosen = await cal.process_selection(callback, callback_data)
    if not selected:
        return
    chosen_date: date = chosen.date() if hasattr(chosen, "date") else chosen
    if not in_period(chosen_date, data["year"], data["month"]):
        await callback.message.answer(
            "Дата вне месяца периода, выберите другую:",
            reply_markup=await start_bounded_calendar(data["year"], data["month"]))
        return
    await ExpenseRepo.update_field(db, data["expense_id"], "date",
                                   chosen_date.isoformat(), db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await _back_to_card(callback.message, state, db, data["expense_id"])


@router.callback_query(EditExpenseFSM.editing_payer, F.data.startswith("setpayer:"))
async def edit_payer(callback: CallbackQuery, state: FSMContext, db: Database,
                     db_user, bot: Bot) -> None:
    data = await state.get_data()
    await ExpenseRepo.update_field(db, data["expense_id"], "payer_id",
                                   int(callback.data.split(":")[1]), db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await callback.message.delete()
    await _back_to_card(callback.message, state, db, data["expense_id"])
    await callback.answer()


@router.message(EditExpenseFSM.editing_description, F.text)
async def edit_description(message: Message, state: FSMContext, db: Database,
                           db_user, bot: Bot) -> None:
    data = await state.get_data()
    await ExpenseRepo.update_field(db, data["expense_id"], "description",
                                   message.text.strip()[:200], db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await _back_to_card(message, state, db, data["expense_id"])


@router.callback_query(EditExpenseFSM.confirming_delete, F.data == "expdel:yes")
async def delete_expense(callback: CallbackQuery, state: FSMContext, db: Database,
                         db_user, bot: Bot) -> None:
    data = await state.get_data()
    e = await ExpenseRepo.get(db, data["expense_id"])
    await ExpenseRepo.soft_delete(db, data["expense_id"], db_user["id"])
    await _after_edit(bot, db, data["expense_id"], db_user)
    await state.clear()
    await callback.message.edit_text(
        f"🗑 Трата #{data['expense_id']} на {fmt_money(e['amount'])} удалена.")
    await callback.answer("Удалено")
