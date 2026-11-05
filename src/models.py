"""Проверяет входные данные и задаёт единый формат ответа всех моделей."""

from dataclasses import dataclass, field
import json
import math


class InputError(ValueError):
    """Сообщает о данных, которые пользователь должен исправить перед запуском."""


class ServiceError(RuntimeError):
    """Содержит безопасное для интерфейса описание сбоя внешнего сервиса."""


@dataclass
class Product:
    """Хранит сведения одного исполнения; пустые характеристики сохраняет для уточнения."""

    name: str
    manufacturer: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    description: str = ""
    url: str = ""
    product_code: str = ""


def unique_object(pairs):
    """Отклоняет повторные ключи JSON до того, как одно значение затрёт другое."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Повторный ключ JSON: {key}.")
        result[key] = value
    return result


def parse_product(raw: str) -> Product:
    """Проверяет JSON до сетевых запросов, не подменяя неверные типы значениями по умолчанию."""
    if len(raw) > 60_000:
        raise InputError("Входной JSON слишком большой: максимум 60 000 символов.")
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
    except InputError:
        raise
    except (ValueError, RecursionError) as exc:
        raise InputError("Некорректный JSON. Проверьте кавычки, запятые и скобки.") from exc
    if not isinstance(data, dict):
        raise InputError("Ожидается JSON-объект одного товара.")
    allowed = set(Product.__dataclass_fields__)
    if set(data) - allowed:
        raise InputError("Неизвестные поля: " + ", ".join(sorted(set(data) - allowed)))
    for key in allowed - {"specs"}:
        value = data.get(key, "")
        if not isinstance(value, str):
            raise InputError(f"Поле {key} должно быть строкой.")
        data[key] = value.strip()
    if not data["name"]:
        raise InputError("Укажите название товара в поле name.")
    specs = data.get("specs", {})
    if not isinstance(specs, dict) or len(specs) > 80:
        raise InputError("specs должен быть объектом максимум из 80 характеристик.")
    clean = {}
    for key, value in specs.items():
        if not key.strip() or not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise InputError("Характеристика должна иметь непустое имя и строковое или числовое значение.")
        if isinstance(value, float) and not math.isfinite(value):
            raise InputError("Значение характеристики должно быть конечным числом.")
        name = key.strip()
        if name in clean:
            raise InputError(f"Повторная характеристика после удаления пробелов: {name}.")
        clean[name] = str(value).strip()
    return Product(**{**data, "specs": clean})


CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "seo_title": {"type": "string"},
        "seo_description": {"type": "string"},
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "commercial": {"type": "string"},
    },
    "required": ["seo_title", "seo_description", "search_queries", "commercial"],
    "additionalProperties": False,
}


def decode_card(raw: str) -> dict:
    """Принимает только ожидаемую структуру; Markdown-обёртку допускает для слабых моделей."""
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise ValueError("Модель должна вернуть текстовый JSON размером до 100 000 символов.")
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        card = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Модель вернула некорректный JSON.") from exc
    if not isinstance(card, dict) or set(card) != set(CARD_SCHEMA["required"]):
        raise ValueError("Ответ должен содержать только четыре поля схемы карточки.")
    for key in ("seo_title", "seo_description", "commercial"):
        if not isinstance(card[key], str) or not card[key].strip():
            raise ValueError(f"Модель не заполнила текстовое поле {key}.")
        card[key] = card[key].strip()
    queries = card["search_queries"]
    if not isinstance(queries, list) or any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError("search_queries должен быть списком непустых строк.")
    card["search_queries"] = [q.strip() for q in queries]
    return card
