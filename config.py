"""Конфигурация бота. Все значения берутся из переменных окружения (.env)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_tg_id: int
    db_path: str
    timezone: str
    settle_day: int     # день месяца, когда стартует расчёт (по умолчанию 1-е)
    settle_hour: int    # час старта расчёта
    remind_hour: int    # час ежедневного напоминания неподтвердившим
    proxy_url: str | None  # прокси для подключения к Telegram API (http/socks5), None — без прокси


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin = os.getenv("ADMIN_TG_ID", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    if not admin.lstrip("-").isdigit():
        raise RuntimeError("ADMIN_TG_ID не задан в .env")
    return Config(
        bot_token=token,
        admin_tg_id=int(admin),
        db_path=os.getenv("DB_PATH", "splitbot.sqlite3"),
        timezone=os.getenv("TZ", "Europe/Berlin"),
        settle_day=int(os.getenv("SETTLE_DAY", "1")),
        settle_hour=int(os.getenv("SETTLE_HOUR", "10")),
        remind_hour=int(os.getenv("REMIND_HOUR", "12")),
        proxy_url=os.getenv("PROXY_URL", "").strip() or None,
    )
