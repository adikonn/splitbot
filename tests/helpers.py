"""Хелперы тестов: фейковый Bot и фабрики моков Message/CallbackQuery."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock


class FakeBot:
    """Записывает все send_message; для tg_id из fail_for бросает исключение
    (имитация заблокировавшего бота пользователя)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, object]] = []
        self.fail_for: set[int] = set()

    async def send_message(self, chat_id: int, text: str,
                           reply_markup=None, **kwargs) -> None:
        if chat_id in self.fail_for:
            raise RuntimeError("bot was blocked by the user")
        self.sent.append((chat_id, text, reply_markup))

    def texts_for(self, chat_id: int) -> list[str]:
        return [t for c, t, _ in self.sent if c == chat_id]

    def markup_for(self, chat_id: int):
        return [m for c, _, m in self.sent if c == chat_id]


def fake_message(text: str = "", user_id: int = 200,
                 username: str | None = "bob") -> AsyncMock:
    m = AsyncMock(name="Message")
    m.text = text
    m.from_user = SimpleNamespace(id=user_id, username=username)
    return m


def fake_callback(data: str = "", user_id: int = 200) -> AsyncMock:
    c = AsyncMock(name="CallbackQuery")
    c.data = data
    c.from_user = SimpleNamespace(id=user_id, username=None)
    c.message = AsyncMock(name="CallbackQuery.message")
    return c


def edited_text(callback: AsyncMock) -> str:
    """Текст последнего edit_text у callback.message."""
    assert callback.message.edit_text.await_count > 0
    return callback.message.edit_text.await_args.args[0]


def answered_text(message: AsyncMock) -> str:
    """Текст последнего message.answer."""
    assert message.answer.await_count > 0
    return message.answer.await_args.args[0]
