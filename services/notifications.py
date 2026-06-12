"""Рассылки. Любая отправка обёрнута в try — заблокировавший бота участник
не должен ронять цикл."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from db.database import Database
from db.repositories import UserRepo

log = logging.getLogger(__name__)


async def send_safe(bot: Bot, tg_id: int, text: str,
                    kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await bot.send_message(tg_id, text, reply_markup=kb)
    except Exception as e:  # noqa: BLE001
        log.warning("Не доставлено tg_id=%s: %s", tg_id, e)


async def broadcast(bot: Bot, db: Database, text: str,
                    kb: InlineKeyboardMarkup | None = None,
                    exclude_tg: set[int] | None = None) -> None:
    for user in await UserRepo.active(db):
        if exclude_tg and user["tg_id"] in exclude_tg:
            continue
        await send_safe(bot, user["tg_id"], text, kb)
