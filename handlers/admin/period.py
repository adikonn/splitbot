"""Админ: управление периодом — ручной запуск расчёта и принудительное закрытие."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db.database import Database
from db.repositories import ConfirmationRepo, PeriodRepo, UserRepo
from services import period_service
from utils import period_title

router = Router(name="admin_period")


@router.callback_query(F.data == "adm:period")
async def period_menu(callback: CallbackQuery, db: Database) -> None:
    open_p = await PeriodRepo.by_status(db, "open")
    conf_p = await PeriodRepo.by_status(db, "confirming")
    lines = ["🔄 <b>Период</b>"]
    rows: list[list[InlineKeyboardButton]] = []
    if open_p:
        lines.append(f"Открыт: {period_title(open_p['year'], open_p['month'])}")
    if conf_p:
        confirmed = await ConfirmationRepo.user_ids(db, conf_p["id"])
        active = await UserRepo.active(db)
        lines.append(
            f"Подтверждается: {period_title(conf_p['year'], conf_p['month'])} "
            f"({len(confirmed)}/{len(active)} подтвердили)")
        rows.append([InlineKeyboardButton(text="⛔ Принудительно закрыть",
                                          callback_data="adm:forceclose")])
    elif open_p:
        rows.append([InlineKeyboardButton(text="▶️ Запустить расчёт сейчас",
                                          callback_data="adm:settle")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")])
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "adm:settle")
async def manual_settle(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    started = await period_service.start_settlement(bot, db)
    await callback.answer(
        "Расчёт запущен, всем разослано превью." if started
        else "Нельзя: нет открытого периода или предыдущий расчёт не закрыт.",
        show_alert=True)
    if started:
        await callback.message.edit_text("▶️ Расчёт запущен.")


@router.callback_query(F.data == "adm:forceclose")
async def force_close_ask(callback: CallbackQuery, db: Database) -> None:
    period = await PeriodRepo.by_status(db, "confirming")
    if not period:
        await callback.answer("Нет периода в фазе подтверждения.", show_alert=True)
        return
    confirmed = await ConfirmationRepo.user_ids(db, period["id"])
    waiting = [u["full_name"] for u in await UserRepo.active(db)
               if u["id"] not in confirmed]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⛔ Да, закрыть", callback_data="adm:forceclose:yes"),
        InlineKeyboardButton(text="◀️ Нет", callback_data="adm:period"),
    ]])
    text = (f"Закрыть расчёт за {period_title(period['year'], period['month'])} "
            "принудительно?")
    if waiting:
        text += "\nНе подтвердили: " + ", ".join(waiting)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "adm:forceclose:yes")
async def force_close_do(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    period = await PeriodRepo.by_status(db, "confirming")
    if not period:
        await callback.answer("Период уже закрыт.", show_alert=True)
        return
    await period_service.close_period(bot, db, period["id"], forced=True)
    await callback.message.edit_text("🔒 Период закрыт принудительно, итоги разосланы.")
    await callback.answer()
