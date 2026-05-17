"""Слой работы с базой данных. SQLite + aiosqlite, без сторонних ORM."""
from __future__ import annotations

import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    created_at     TEXT NOT NULL,
    trial_ends_at  TEXT NOT NULL,
    paid_until     TEXT,
    photos_analyzed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meal_reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    remind_at   TEXT NOT NULL,
    bje_amount  REAL NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending
    ON meal_reminders(sent, remind_at);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    amount          INTEGER NOT NULL,
    currency        TEXT NOT NULL,
    telegram_payment_charge_id TEXT,
    provider_payment_charge_id TEXT,
    paid_at         TEXT NOT NULL,
    days_added      INTEGER NOT NULL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s)


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    # ---------------- users ----------------

    async def get_or_create_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
    ) -> dict:
        """Возвращает запись пользователя, создавая при первом обращении с триалом."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if row:
                # Обновим имя/username на случай изменения
                await db.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username, first_name, user_id),
                )
                await db.commit()
                return dict(row)

            now = _utcnow()
            trial_ends = now + timedelta(days=config.trial_days)
            await db.execute(
                """INSERT INTO users
                   (user_id, username, first_name, created_at, trial_ends_at, photos_analyzed)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (user_id, username, first_name, _iso(now), _iso(trial_ends)),
            )
            await db.commit()
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(await cur.fetchone())

    async def has_access(self, user_id: int) -> tuple[bool, str]:
        """Возвращает (есть_ли_доступ, причина). Причина: 'trial' | 'paid' | 'expired'."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return False, "expired"

            now = _utcnow()
            paid_until = _parse(row["paid_until"])
            trial_ends = _parse(row["trial_ends_at"])

            if paid_until and paid_until > now:
                return True, "paid"
            if trial_ends and trial_ends > now:
                return True, "trial"
            return False, "expired"

    async def access_info(self, user_id: int) -> dict:
        """Подробная информация о доступе для команды /status."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return {"exists": False}
            data = dict(row)
            now = _utcnow()
            paid_until = _parse(data["paid_until"])
            trial_ends = _parse(data["trial_ends_at"])
            data["now"] = now
            data["paid_until_dt"] = paid_until
            data["trial_ends_dt"] = trial_ends
            data["exists"] = True
            return data

    async def increment_photo_count(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET photos_analyzed = photos_analyzed + 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    async def extend_subscription(self, user_id: int, days: int) -> datetime:
        """Продляет платную подписку на N дней от max(сейчас, текущий paid_until)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT paid_until FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cur.fetchone()
            base = _utcnow()
            if row and row["paid_until"]:
                existing = _parse(row["paid_until"])
                if existing and existing > base:
                    base = existing
            new_until = base + timedelta(days=days)
            await db.execute(
                "UPDATE users SET paid_until = ? WHERE user_id = ?",
                (_iso(new_until), user_id),
            )
            await db.commit()
            return new_until

    # ---------------- reminders ----------------

    async def add_reminder(self, user_id: int, remind_at: datetime, bje: float) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """INSERT INTO meal_reminders (user_id, remind_at, bje_amount, sent, created_at)
                   VALUES (?, ?, ?, 0, ?)""",
                (user_id, _iso(remind_at), bje, _iso(_utcnow())),
            )
            await db.commit()
            return cur.lastrowid

    async def fetch_due_reminders(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM meal_reminders WHERE sent = 0 AND remind_at <= ?",
                (_iso(_utcnow()),),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def mark_reminder_sent(self, reminder_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE meal_reminders SET sent = 1 WHERE id = ?", (reminder_id,)
            )
            await db.commit()

    # ---------------- payments ----------------

    async def record_payment(
        self,
        user_id: int,
        amount: int,
        currency: str,
        telegram_charge_id: str | None,
        provider_charge_id: str | None,
        days_added: int,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO payments
                   (user_id, amount, currency, telegram_payment_charge_id,
                    provider_payment_charge_id, paid_at, days_added)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, amount, currency,
                    telegram_charge_id, provider_charge_id,
                    _iso(_utcnow()), days_added,
                ),
            )
            await db.commit()


db = Database(config.db_path)
