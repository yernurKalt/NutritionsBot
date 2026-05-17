"""Обработчики Telegram: команды, фото, оплата."""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
)

from config import config
from database import db
from ai_analyzer import analyze_food_image, format_analysis

log = logging.getLogger(__name__)
router = Router()


# ---------- утилиты ----------

def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def _subscribe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscribe"),
        ]]
    )


# ---------- /start, /help ----------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    record = await db.get_or_create_user(user.id, user.username, user.first_name)
    trial_ends = datetime.fromisoformat(record["trial_ends_at"])
    trial_left = trial_ends - datetime.now(timezone.utc)

    is_new = record["photos_analyzed"] == 0 and trial_left > timedelta(days=config.trial_days - 1)

    if is_new:
        greeting = (
            f"Привет, {user.first_name or 'друг'}! 👋\n\n"
            "Я помогаю людям с диабетом и тем, кто следит за питанием: "
            "по *фотографии блюда* определяю калории, БЖУ, "
            "*хлебные единицы (ХЕ)* и *белково-жировые единицы (БЖЕ)*, "
            "а через 2 часа напомню проверить сахар, если в еде были БЖЕ.\n\n"
            f"🎁 Вам открыт *бесплатный пробный период на {config.trial_days} дня* — "
            "пользуйтесь без ограничений.\n\n"
            "📸 Просто пришлите фото еды.\n\n"
            "Команды:\n"
            "/status — статус подписки\n"
            "/subscribe — оформить подписку\n"
            "/help — справка"
        )
    else:
        greeting = (
            f"С возвращением, {user.first_name or 'друг'}!\n\n"
            "📸 Пришлите фото еды, и я рассчитаю КБЖУ, ХЕ и БЖЕ.\n\n"
            "/status — статус подписки"
        )
    await message.answer(greeting, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🤖 *Как пользоваться:*\n\n"
        "1. Сфотографируйте блюдо целиком, при хорошем свете.\n"
        "2. Отправьте фото в чат.\n"
        "3. Получите расчёт: калории, БЖУ, ХЕ, ГИ, БЖЕ.\n"
        "4. Если в еде есть БЖЕ — через 2 часа я пришлю напоминание.\n\n"
        "⚠️ Все расчёты приблизительные. Решения по дозе инсулина "
        "принимайте на основании показаний глюкометра и совета врача.\n\n"
        "Команды: /start /status /subscribe",
        parse_mode="Markdown",
    )


# ---------- /status ----------

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if message.from_user is None:
        return
    info = await db.access_info(message.from_user.id)
    if not info["exists"]:
        await message.answer("Сначала нажмите /start.")
        return

    now = info["now"]
    trial = info["trial_ends_dt"]
    paid = info["paid_until_dt"]

    lines = ["📊 *Статус подписки*\n"]

    if paid and paid > now:
        left = paid - now
        lines.append(f"✅ Платная подписка активна до *{_fmt_dt(paid)}* (осталось {left.days} дн.)")
    elif trial and trial > now:
        left = trial - now
        hours = int(left.total_seconds() // 3600)
        lines.append(f"🎁 Пробный период активен ещё *{hours} ч.* (до {_fmt_dt(trial)})")
    else:
        lines.append("❌ Доступ закончился. Оформите подписку, чтобы продолжить.")

    lines.append(f"\n📸 Проанализировано фото: *{info['photos_analyzed']}*")
    lines.append(
        f"\nСтоимость подписки: *{config.subscription_price / 100:.0f} "
        f"{config.subscription_currency}* / {config.subscription_days} дней"
    )

    kb = None if (paid and paid > now) else _subscribe_kb()
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=kb)


# ---------- /subscribe и оплата ----------

@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, bot: Bot) -> None:
    await _send_invoice(bot, message.chat.id)


@router.callback_query(F.data == "subscribe")
async def cb_subscribe(callback, bot: Bot) -> None:
    await callback.answer()
    await _send_invoice(bot, callback.message.chat.id)


async def _send_invoice(bot: Bot, chat_id: int) -> None:
    if not config.payment_provider_token:
        await bot.send_message(
            chat_id,
            "⚠️ Оплата временно недоступна: администратор не настроил платёжный провайдер.\n"
            "Напишите владельцу бота.",
        )
        return

    price = LabeledPrice(
        label=f"Подписка на {config.subscription_days} дней",
        amount=config.subscription_price,
    )
    await bot.send_invoice(
        chat_id=chat_id,
        title="Подписка FoodAnalyzer",
        description=(
            f"Безлимитный анализ фото еды на {config.subscription_days} дней. "
            "Расчёт КБЖУ, ХЕ, БЖЕ, ГИ и напоминания о БЖЕ через 2 часа."
        ),
        payload=f"sub_{config.subscription_days}d",
        provider_token=config.payment_provider_token,
        currency=config.subscription_currency,
        prices=[price],
        start_parameter="subscribe",
    )


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, bot: Bot) -> None:
    # Здесь можно валидировать payload / проверять пользователя
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if sp is None or message.from_user is None:
        return
    user_id = message.from_user.id

    new_until = await db.extend_subscription(user_id, config.subscription_days)
    await db.record_payment(
        user_id=user_id,
        amount=sp.total_amount,
        currency=sp.currency,
        telegram_charge_id=sp.telegram_payment_charge_id,
        provider_charge_id=sp.provider_payment_charge_id,
        days_added=config.subscription_days,
    )

    await message.answer(
        "✅ *Оплата получена, спасибо!*\n\n"
        f"Подписка активна до *{_fmt_dt(new_until)}*.\n"
        "Можете присылать фото — без ограничений.",
        parse_mode="Markdown",
    )


# ---------- фото еды ----------

@router.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    user = message.from_user
    await db.get_or_create_user(user.id, user.username, user.first_name)

    has_access, reason = await db.has_access(user.id)
    if not has_access:
        await message.answer(
            "❌ Бесплатный пробный период закончился.\n\n"
            f"Оформите подписку — *{config.subscription_price / 100:.0f} "
            f"{config.subscription_currency}* за {config.subscription_days} дней — "
            "и продолжайте пользоваться без ограничений.",
            parse_mode="Markdown",
            reply_markup=_subscribe_kb(),
        )
        return

    # Берём фото максимального размера
    largest = message.photo[-1]
    status_msg = await message.answer("🔍 Анализирую блюдо…")

    try:
        buf = io.BytesIO()
        await bot.download(largest, destination=buf)
        buf.seek(0)
        image_bytes = buf.read()

        analysis = await analyze_food_image(image_bytes)
    except Exception:
        log.exception("Ошибка анализа фото user_id=%s", user.id)
        await status_msg.edit_text(
            "😔 Не получилось проанализировать фото. Попробуйте ещё раз или "
            "пришлите другое фото с лучшим освещением."
        )
        return

    text = format_analysis(analysis)
    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        # Markdown иногда ломается на спецсимволах из ответа модели — отправим plain
        await status_msg.edit_text(text)

    await db.increment_photo_count(user.id)

    # Планируем напоминание о БЖЕ
    if analysis.is_food and analysis.needs_bje_reminder \
            and analysis.protein_fat_units_bje >= config.bje_reminder_threshold:
        remind_at = datetime.now(timezone.utc) + timedelta(hours=config.bje_reminder_hours)
        await db.add_reminder(user.id, remind_at, analysis.protein_fat_units_bje)
        await message.answer(
            f"⏰ Напомню о проверке сахара через {config.bje_reminder_hours} ч.",
        )


# ---------- любые другие сообщения ----------

@router.message()
async def on_other(message: Message) -> None:
    await message.answer(
        "📸 Пришлите *фотографию блюда*, и я рассчитаю КБЖУ, ХЕ и БЖЕ.\n\n"
        "Команды: /start /status /subscribe /help",
        parse_mode="Markdown",
    )
