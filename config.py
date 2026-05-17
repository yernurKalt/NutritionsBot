"""Конфигурация бота. Все значения берутся из переменных окружения / .env."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Не задана переменная окружения {key}. См. .env.example")
    return val or ""


@dataclass(frozen=True)
class Config:
    bot_token: str = _env("BOT_TOKEN", required=True)
    gemini_api_key: str = _env("GEMINI_API_KEY", required=True)
    gemini_model: str = _env("GEMINI_MODEL", "gemini-2.5-flash")

    payment_provider_token: str = _env("PAYMENT_PROVIDER_TOKEN", "")

    subscription_price: int = int(_env("SUBSCRIPTION_PRICE", "49900"))
    subscription_currency: str = _env("SUBSCRIPTION_CURRENCY", "RUB")
    subscription_days: int = int(_env("SUBSCRIPTION_DAYS", "30"))

    trial_days: int = int(_env("TRIAL_DAYS", "2"))
    bje_reminder_hours: int = int(_env("BJE_REMINDER_HOURS", "2"))
    bje_reminder_threshold: float = float(_env("BJE_REMINDER_THRESHOLD", "1.0"))

    db_path: str = _env("DB_PATH", "food_bot.db")


config = Config()
