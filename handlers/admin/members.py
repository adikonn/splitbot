"""Админ: заявки на вступление и управление составом коллектива."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db.database import Database
from db.repositories import UserRepo
from services import membership
from services.membership import request_kb

router = Router(name="admin_members")


# ----------------------------- заявки ---------------------------------------

@router.callback_query(F.data == "adm:requests")
async def list_requests(callback: CallbackQuery, db: Database) -> None:
    pending = await UserRepo.pending(db)
    if not pending:
        await callback.answer("Новых заявок нет.", show_alert=True)
        return
    await callback.message.edit_text("📨 Заявки на вступление:")
    for u in pending:
        uname = f" (@{u['username']})" if u["username"] else ""
        await callback.message.answer(f"<b>{u['full_name']}</b>{uname}",
                                      reply_markup=request_kb(u["id"]))
    await callback.answer()


@router.callback_query(F.data.startswith("req:approve:"))
async def approve_request(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    result = await membership.approve(bot, db, int(callback.data.split(":")[2]))
    await callback.message.edit_text(result)
    await callback.answer()


@router.callback_query(F.data.startswith("req:reject:"))
async def reject_request(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    result = await membership.reject(bot, db, int(callback.data.split(":")[2]))
    await callback.message.edit_text(result)
    await callback.answer()


# ----------------------------- состав ---------------------------------------

@router.callback_query(F.data == "adm:members")
async def list_members(callback: CallbackQuery, db: Database) -> None:
    users = await UserRepo.active(db)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        *[[InlineKeyboardButton(
            text=("👑 " if u["role"] == "admin" else "") + u["full_name"],
            callback_data=f"adm:member:{u['id']}")] for u in users],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")],
    ])
    await callback.message.edit_text(f"👥 Участники ({len(users)}):", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:member:"))
async def member_card(callback: CallbackQuery, db: Database) -> None:
    user = await UserRepo.get(db, int(callback.data.split(":")[2]))
    if not user:
        await callback.answer("Не найден.", show_alert=True)
        return
    uname = f"@{user['username']}" if user["username"] else "—"
    rows = [[InlineKeyboardButton(text="◀️ Назад", callback_data="adm:members")]]
    if user["role"] != "admin" and user["status"] == "active":
        rows.insert(0, [InlineKeyboardButton(
            text="🗑 Исключить из коллектива", callback_data=f"adm:rm:{user['id']}")])
    await callback.message.edit_text(
        f"<b>{user['full_name']}</b>\nusername: {uname}\n"
        f"роль: {user['role']}\nв коллективе с {user['created_at'][:10]}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:rm:") & ~F.data.startswith("adm:rmyes:"))
async def remove_confirm(callback: CallbackQuery, db: Database) -> None:
    user_id = int(callback.data.split(":")[2])
    user = await UserRepo.get(db, user_id)
    if not user:
        await callback.answer("Не найден.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, исключить", callback_data=f"adm:rmyes:{user_id}"),
        InlineKeyboardButton(text="◀️ Нет", callback_data=f"adm:member:{user_id}"),
    ]])
    await callback.message.edit_text(
        f"Исключить <b>{user['full_name']}</b>?\n"
        "Его/её траты текущего периода сохранятся, но в дележе новых трат "
        "участник участвовать не будет.", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:rmyes:"))
async def remove_do(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    result = await membership.remove_member(bot, db, int(callback.data.split(":")[2]))
    await callback.message.edit_text(result)
    await callback.answer()
