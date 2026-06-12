"""Членство в коллективе: заявки, одобрение/отклонение, удаление участника."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.database import Database
from db.repositories import UserRepo
from keyboards.common import main_menu
from services.notifications import send_safe


def request_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"req:approve:{user_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"req:reject:{user_id}"),
    ]])


async def submit_request(bot: Bot, db: Database, admin_tg_id: int,
                         tg_id: int, username: str | None, full_name: str) -> None:
    """Создаёт/обновляет заявку и шлёт карточку админу."""
    user = await UserRepo.get_by_tg(db, tg_id)
    if user is None:
        user_id = await UserRepo.create(db, tg_id, username, full_name,
                                        role="member", status="pending")
    else:
        await UserRepo.reapply(db, user["id"], username, full_name)
        user_id = user["id"]
    uname = f" (@{username})" if username else ""
    await send_safe(
        bot, admin_tg_id,
        f"📨 Новая заявка на вступление: <b>{full_name}</b>{uname}",
        request_kb(user_id),
    )


async def approve(bot: Bot, db: Database, user_id: int) -> str:
    user = await UserRepo.get(db, user_id)
    if not user or user["status"] != "pending":
        return "Заявка уже обработана."
    await UserRepo.set_status(db, user_id, "active")
    await send_safe(bot, user["tg_id"],
                    "🎉 Ваша заявка одобрена — добро пожаловать в коллектив!")
    try:
        await bot.send_message(user["tg_id"], "Главное меню:",
                               reply_markup=main_menu(is_admin=False))
    except Exception:  # noqa: BLE001
        pass
    return f"✅ {user['full_name']} принят(а) в коллектив."


async def reject(bot: Bot, db: Database, user_id: int) -> str:
    user = await UserRepo.get(db, user_id)
    if not user or user["status"] != "pending":
        return "Заявка уже обработана."
    await UserRepo.set_status(db, user_id, "removed")
    await send_safe(bot, user["tg_id"], "К сожалению, ваша заявка отклонена.")
    return f"❌ Заявка {user['full_name']} отклонена."


async def remove_member(bot: Bot, db: Database, user_id: int) -> str:
    user = await UserRepo.get(db, user_id)
    if not user or user["status"] != "active":
        return "Участник не найден или уже удалён."
    if user["role"] == "admin":
        return "Нельзя удалить администратора."
    await UserRepo.set_status(db, user_id, "removed")
    await send_safe(bot, user["tg_id"], "Вы исключены из коллектива администратором.")
    return f"🗑 {user['full_name']} исключён(а). Его/её траты сохранены."
