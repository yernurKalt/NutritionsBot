# 🍽 FoodAnalyzer Bot (Gemini)

Telegram-бот для людей с диабетом и тех, кто следит за питанием. По фото блюда считает калории, БЖУ, **хлебные единицы (ХЕ)**, **белково-жировые единицы (БЖЕ)** и гликемический индекс. Через 2 часа напоминает проверить сахар, если в еде были БЖЕ.

**Анализ работает на бесплатном Google Gemini API.**

## Возможности

- 📸 Анализ блюда по фото через Gemini Vision (бесплатно).
- 🥖 Расчёт ХЕ (хлебных единиц) и БЖЕ (белково-жировых единиц).
- ⏰ Автоматическое напоминание через 2 часа о возможном отложенном подъёме сахара.
- 🎁 Пробный период 2 дня для новых пользователей.
- 💳 Платная подписка через Telegram Payments (ЮKassa, Stripe и др.).

## Бесплатные лимиты Gemini

На момент написания у Google AI Studio есть бесплатный тариф для моделей `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash`:
- ~15 запросов в минуту,
- ~1500 запросов в сутки,
- ~1 млн токенов в день.

Лимиты периодически меняются — актуальные смотрите на [ai.google.dev/pricing](https://ai.google.dev/pricing).

## Структура

```
food_bot/
├── bot.py            # точка входа
├── config.py         # настройки из .env
├── database.py       # SQLite: пользователи, напоминания, платежи
├── ai_analyzer.py    # анализ фото через Gemini
├── handlers.py       # обработчики команд и сообщений
├── scheduler.py      # фоновая отправка напоминаний
├── requirements.txt
└── .env.example
```

## Быстрый старт

### 1. Получите ключи

- **BOT_TOKEN** — у [@BotFather](https://t.me/BotFather) (`/newbot`).
- **GEMINI_API_KEY** — бесплатно на [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- **PAYMENT_PROVIDER_TOKEN** — у `@BotFather` → ваш бот → **Payments** → выбрать провайдера (ЮKassa, Stripe и т.п.). Для теста есть тестовые токены.

### 2. Установите зависимости

```bash
cd food_bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Настройте `.env`

```bash
cp .env.example .env
# отредактируйте .env, подставьте свои ключи
```

### 4. Запустите

```bash
python bot.py
```

## Команды

| Команда     | Описание                          |
|-------------|-----------------------------------|
| `/start`    | Приветствие, активирует триал     |
| `/help`     | Справка                           |
| `/status`   | Статус подписки                   |
| `/subscribe`| Оформить или продлить подписку    |

## Как работает анализ

1. Пользователь присылает фото.
2. Бот скачивает фото и передаёт его в Gemini Vision с system_instruction и JSON-схемой.
3. Gemini возвращает строго валидный JSON (благодаря `response_mime_type="application/json"` + `response_schema`).
4. JSON парсится в `FoodAnalysis` и форматируется в человекочитаемое сообщение.
5. Если `needs_bje_reminder=true` и БЖЕ ≥ порога — в таблицу `meal_reminders` ставится запись.
6. Шедулер каждую минуту проверяет `meal_reminders` и шлёт уведомления через 2 часа.

## Выбор модели

В `.env` можно указать `GEMINI_MODEL`:

| Модель                  | Качество | Скорость | Под что подходит            |
|-------------------------|----------|----------|------------------------------|
| `gemini-2.5-flash`      | ⭐⭐⭐⭐    | ⭐⭐⭐⭐    | По умолчанию, баланс         |
| `gemini-2.5-flash-lite` | ⭐⭐⭐     | ⭐⭐⭐⭐⭐  | Экономия лимитов             |
| `gemini-2.0-flash`      | ⭐⭐⭐⭐    | ⭐⭐⭐⭐    | Альтернатива 2.5             |
| `gemini-2.5-pro`        | ⭐⭐⭐⭐⭐  | ⭐⭐      | Сложные блюда, но платно     |

## Подписка и оплата

- Новый пользователь автоматически получает `TRIAL_DAYS` (по умолчанию 2) дня бесплатного доступа.
- После окончания триала фото перестают приниматься, бот предлагает оформить подписку.
- Платежи проходят через Telegram Payments (`send_invoice` → `pre_checkout_query` → `successful_payment`).
- На каждое успешное `successful_payment` `paid_until` пользователя продляется на `SUBSCRIPTION_DAYS`.
- Все платежи сохраняются в таблицу `payments` для аудита.

## Деплой

systemd-сервис:

```ini
# /etc/systemd/system/foodbot.service
[Unit]
Description=FoodAnalyzer Telegram Bot
After=network.target

[Service]
Type=simple
User=foodbot
WorkingDirectory=/opt/foodbot
Environment="PATH=/opt/foodbot/.venv/bin"
ExecStart=/opt/foodbot/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now foodbot
sudo journalctl -u foodbot -f
```

## Важно

⚠️ Все расчёты приблизительные. Бот не заменяет врача. Решения по дозировке инсулина должны основываться на показаниях глюкометра и рекомендациях эндокринолога.

⚠️ Не отправляйте через бот персональные медицинские данные — фотографии и метаданные обрабатываются Google Gemini API в соответствии с [политикой Google](https://ai.google.dev/gemini-api/terms).
