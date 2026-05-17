"""Шедулер напоминаний о БЖЕ через 2 часа после еды."""
from __future__ import annotations

import logging
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import db

log = logging.getLogger(__name__)


async def _check_and_send(bot: Bot) -> None:
    try:
        due = await db.fetch_due_reminders()
    except Exception:
        log.exception("Не удалось получить напоминания")
        return

    for r in due:
        text = (
            "🔔 *Напоминание о БЖЕ*\n\n"
            f"Обратите внимание: пища, которую вы приняли ~2 часа назад, "
            f"содержала *{r['bje_amount']:.1f} БЖЕ* (белково-жировых единиц).\n\n"
            "Проверьте уровень сахара в крови — возможно, необходима "
            "дополнительная компенсация инсулином."
        )
        try:
            await bot.send_message(r["user_id"], text, parse_mode="Markdown")
        except Exception:
            log.warning("Не удалось отправить напоминание user_id=%s", r["user_id"], exc_info=True)
        finally:
            await db.mark_reminder_sent(r["id"])


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Запускает шедулер, проверяющий напоминания каждую минуту."""
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(_check_and_send, "interval", minutes=1, args=[bot], id="bje_reminders")
    sched.start()
    log.info("Шедулер напоминаний запущен")
    return sched
