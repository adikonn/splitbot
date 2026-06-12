"""Общие фикстуры."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config
from db.database import Database
from db.repositories import PeriodRepo, UserRepo
from tests.helpers import FakeBot

# tg_id участников в тестах
ADMIN_TG, BOB_TG, EVA_TG = 100, 200, 300


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def seeded(db):
    """Админ + два участника + открытый период 2026-06."""
    admin = await UserRepo.create(db, ADMIN_TG, "adm", "Админ", "admin", "active")
    bob = await UserRepo.create(db, BOB_TG, "bob", "Боб", "member", "active")
    eva = await UserRepo.create(db, EVA_TG, None, "Ева", "member", "active")
    period = await PeriodRepo.create_open(db, 2026, 6)
    return {"admin": admin, "bob": bob, "eva": eva, "period": period}


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def config(tmp_path):
    return Config(
        bot_token="1:test", admin_tg_id=ADMIN_TG,
        db_path=str(tmp_path / "t.sqlite3"), timezone="UTC",
        settle_day=1, settle_hour=10, remind_hour=12,
    )


@pytest.fixture
def state():
    storage = MemoryStorage()
    return FSMContext(storage=storage,
                      key=StorageKey(bot_id=42, chat_id=1, user_id=1))
