"""Анализ фото блюда через Google Gemini (vision).

Использует google-genai SDK. Преимущество перед обычным prompting:
Gemini поддерживает structured output через response_schema — модель
гарантированно возвращает JSON по нашей схеме.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types

from config import config

log = logging.getLogger(__name__)


_client = genai.Client(api_key=config.gemini_api_key)


SYSTEM_INSTRUCTION = """Ты — нутрициолог-ассистент для людей с диабетом.
По фотографии блюда оцениваешь его пищевую ценность.

Правила оценки:
- Хлебная единица (ХЕ) = 12 г усваиваемых углеводов.
- БЖЕ (белково-жировая единица) = (белки*4 + жиры*9) / 100 ккал.
- Гликемический индекс: <55 низкий, 55-69 средний, >=70 высокий.
- needs_bje_reminder = true, если БЖЕ >= 1.0 ИЛИ жиров >= 20 г на порцию
  (отложенный подъём глюкозы).
- Если на фото нет еды — верни is_food=false и заполни числовые поля нулями.
- Не уклоняйся: лучше дать диапазонную, но конкретную оценку, чем отказ.
- Все названия и описания — на русском языке.
- Все числа — числа, не строки. Без префиксов "около" и т.п.
"""


# JSON-схема для structured output Gemini.
# Описывает поля, которые модель ОБЯЗАНА вернуть.
RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "is_food", "dish_name", "ingredients", "portion_description",
        "total_weight_g", "calories_kcal", "protein_g", "fat_g", "carbs_g",
        "bread_units_he", "glycemic_index", "protein_fat_units_bje",
        "needs_bje_reminder",
    ],
    "properties": {
        "is_food": {"type": "boolean", "description": "true если на фото распознана еда"},
        "dish_name": {"type": "string", "description": "Короткое название блюда на русском"},
        "ingredients": {"type": "string", "description": "Перечень ингредиентов через запятую, на русском"},
        "portion_description": {"type": "string", "description": "Например: '5 котлет, объём порции около 350-400 г'"},
        "total_weight_g": {"type": "number", "description": "Общий вес порции в граммах"},
        "calories_kcal": {"type": "number", "description": "Суммарные ккал"},
        "protein_g": {"type": "number", "description": "Суммарные белки, г"},
        "fat_g": {"type": "number", "description": "Суммарные жиры, г"},
        "carbs_g": {"type": "number", "description": "Суммарные углеводы, г"},
        "bread_units_he": {"type": "number", "description": "Хлебные единицы = углеводы/12"},
        "glycemic_index": {"type": "number", "description": "Средневзвешенный ГИ блюда 0-100"},
        "protein_fat_units_bje": {"type": "number", "description": "БЖЕ = (Б*4 + Ж*9)/100, округлить до 1 знака"},
        "needs_bje_reminder": {"type": "boolean", "description": "true, если стоит напомнить про БЖЕ"},
        "warning": {"type": "string", "description": "Короткое предупреждение или пустая строка"},
    },
}


@dataclass
class FoodAnalysis:
    is_food: bool
    dish_name: str
    ingredients: str
    portion_description: str
    total_weight_g: float
    calories_kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    bread_units_he: float
    glycemic_index: float
    protein_fat_units_bje: float
    needs_bje_reminder: bool
    warning: Optional[str]

    @classmethod
    def from_json(cls, data: dict) -> "FoodAnalysis":
        def num(key: str) -> float:
            v = data.get(key, 0) or 0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        warning = data.get("warning") or None
        if isinstance(warning, str) and not warning.strip():
            warning = None

        return cls(
            is_food=bool(data.get("is_food", False)),
            dish_name=str(data.get("dish_name", "") or ""),
            ingredients=str(data.get("ingredients", "") or ""),
            portion_description=str(data.get("portion_description", "") or ""),
            total_weight_g=num("total_weight_g"),
            calories_kcal=num("calories_kcal"),
            protein_g=num("protein_g"),
            fat_g=num("fat_g"),
            carbs_g=num("carbs_g"),
            bread_units_he=num("bread_units_he"),
            glycemic_index=num("glycemic_index"),
            protein_fat_units_bje=num("protein_fat_units_bje"),
            needs_bje_reminder=bool(data.get("needs_bje_reminder", False)),
            warning=warning,
        )


def _gi_label(gi: float) -> tuple[str, int]:
    if gi < 55:
        return "низкий", int(gi)
    if gi < 70:
        return "средний", int(gi)
    return "высокий", int(gi)


def _pct(part: float, total: float) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(part / total * 100)))


def format_analysis(a: FoodAnalysis) -> str:
    """Готовит красивое сообщение в стиле, который указал пользователь."""
    if not a.is_food:
        return (
            "🤔 На фото не удалось распознать еду.\n\n"
            "Попробуйте сфотографировать блюдо целиком, при хорошем освещении, "
            "сверху или под углом ~45°."
        )

    protein_kcal = a.protein_g * 4
    fat_kcal = a.fat_g * 9
    carb_kcal = a.carbs_g * 4
    total_kcal = max(a.calories_kcal, protein_kcal + fat_kcal + carb_kcal, 1)

    p_pct = _pct(protein_kcal, total_kcal)
    f_pct = _pct(fat_kcal, total_kcal)
    c_pct = _pct(carb_kcal, total_kcal)

    gi_label, gi_pct = _gi_label(a.glycemic_index)
    bje_pct = _pct(fat_kcal, total_kcal)

    parts = [
        f"🍽 *На фото есть следующее блюдо:* {a.dish_name}"
        + (f" ({a.ingredients})" if a.ingredients else "")
        + ".",
    ]
    if a.portion_description:
        parts.append(f"*Примерные значения на {a.portion_description}:*")

    parts.append("*Суммарно во всех продуктах:*")
    parts.append(
        f"• Калории: *{a.calories_kcal:.0f} ккал*\n"
        f"• Белки: *{a.protein_g:.0f} г* ({p_pct}%)\n"
        f"• Жиры: *{a.fat_g:.0f} г* ({f_pct}%)\n"
        f"• Углеводы: *{a.carbs_g:.0f} г* ({c_pct}%) — примерно *{a.bread_units_he:.1f} ХЕ*\n"
        f"• Общий вес: *{a.total_weight_g:.0f} г*\n"
        f"• Гликемический индекс: *{gi_pct} ({gi_label})*"
    )

    if a.needs_bje_reminder:
        parts.append(
            "⚠️ *Внимание!* Продукт содержит белково-жировые единицы (БЖЕ). "
            "В зависимости от общего количества жирной пищи может потребоваться "
            "дополнительно компенсировать БЖУ через 2–3 часа!"
        )
        parts.append(
            f"• Белково-жировые единицы: *{a.fat_g:.0f} г жиров* ({bje_pct}%) — "
            f"*{a.protein_fat_units_bje:.1f} БЖЕ*"
        )

    if a.warning:
        parts.append(f"ℹ️ {a.warning}")

    parts.append("\n_Приятного аппетита!_ 🥗")
    parts.append(
        "\n_Оценка приблизительная. Корректируйте дозу по показаниям глюкометра "
        "и рекомендациям врача._"
    )
    return "\n\n".join(parts)


async def analyze_food_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> FoodAnalysis:
    """Отправляет фото в Gemini и возвращает структурированный результат.

    Использует асинхронный клиент google-genai (client.aio.models).
    response_mime_type='application/json' + response_schema гарантируют,
    что модель вернёт валидный JSON по нашей схеме.
    """
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    response = await _client.aio.models.generate_content(
        model=config.gemini_model,
        contents=[
            image_part,
            "Проанализируй это блюдо и верни данные строго по схеме.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.2,
            max_output_tokens=4096,
        ),
    )

    # Gemini возвращает готовый JSON-текст. На всякий случай парсим вручную.
    raw = response.text or ""
    if not raw.strip():
        # Сафети-фильтры могли отрезать ответ
        log.warning("Gemini вернул пустой ответ. finish_reason=%s",
                    getattr(response.candidates[0], "finish_reason", "?") if response.candidates else "?")
        raise RuntimeError("Пустой ответ от Gemini (возможно, сработал safety-фильтр)")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("Не удалось распарсить JSON от Gemini: %s\nRaw: %s", e, raw[:500])
        raise

    return FoodAnalysis.from_json(data)
