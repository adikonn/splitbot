"""Админ-панель: главное меню и навигация."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from db.database import Database
from db.repositories import PeriodRepo, UserRepo
from keyboards.common import BTN_ADMIN
from utils import period_title

router = Router(name="admin_panel")


async def panel_kb(db: Database) -> InlineKeyboardMarkup:
    pending = len(await UserRepo.pending(db))
    badge = f" ({pending})" if pending else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📨 Заявки{badge}", callback_data="adm:requests")],
        [InlineKeyboardButton(text="👥 Участники", callback_data="adm:members")],
        [InlineKeyboardButton(text="🧾 Траты", callback_data="adm:expenses:0")],
        [InlineKeyboardButton(text="🔄 Период", callback_data="adm:period")],
    ])


async def panel_text(db: Database) -> str:
    lines = ["⚙️ <b>Админ-панель</b>"]
    for status, label in (("open", "открыт"), ("confirming", "идёт подтверждение")):
        p = await PeriodRepo.by_status(db, status)
        if p:
            lines.append(f"• {period_title(p['year'], p['month'])} — {label}")
    return "\n".join(lines)


@router.message(Command("admin"))
@router.message(F.text == BTN_ADMIN)
async def admin_panel(message: Message, db: Database) -> None:
    await message.answer(await panel_text(db), reply_markup=await panel_kb(db))


@router.callback_query(F.data == "adm:back")
async def admin_back(callback: CallbackQuery, db: Database) -> None:
    await callback.message.edit_text(await panel_text(db),
                                     reply_markup=await panel_kb(db))
    await callback.answer()
