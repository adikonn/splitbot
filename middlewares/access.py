"""Контроль доступа.

AccessMiddleware вешается на роутеры участников: пускает только active-пользователей
и кладёт строку users в data['db_user'].
AdminMiddleware — поверх него на админ-роутере: дополнительно требует role = admin.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from db.database import Database
from db.repositories import UserRepo


async def _deny(event: TelegramObject, text: str) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    elif isinstance(event, Message):
        await event.answer(text)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return None
        user = await UserRepo.get_by_tg(self.db, tg_user.id)
        if user is None:
            await _deny(event, "Вы не зарегистрированы. Отправьте /start, чтобы подать заявку.")
            return None
        if user["status"] == "pending":
            await _deny(event, "Ваша заявка ещё на рассмотрении у администратора.")
            return None
        if user["status"] != "active":
            await _deny(event, "Доступ закрыт. Отправьте /start, чтобы подать заявку заново.")
            return None
        data["db_user"] = user
        data["db"] = self.db
        return await handler(event, data)


class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("db_user")
        if user is None or user["role"] != "admin":
            await _deny(event, "Эта функция доступна только администратору.")
            return None
        return await handler(event, data)
