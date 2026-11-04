"""Получает названия моделей для списка выбора без запуска генерации."""

import json
import os
from pathlib import Path

from ..models import ServiceError
from .providers import ModelSettings, PROVIDERS, validate_settings
from ..transport import request_json


def codex_models():
    """Читает видимые модели из локального кэша Codex, не запуская CLI и не читая ключи."""
    folder = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    path = folder / "models_cache.json"
    try:
        if path.stat().st_size > 5_000_000:
            raise ServiceError("Кэш моделей Codex слишком большой.")
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data["models"]
        if not isinstance(models, list):
            raise ValueError
        names = [item["slug"] for item in models if isinstance(item, dict)
                 and item.get("visibility") == "list" and isinstance(item.get("slug"), str)]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise ServiceError("Список Codex недоступен. Откройте авторизованный Codex, затем обновите список.") from None
    if not names:
        raise ServiceError("В кэше Codex нет видимых моделей. Обновите каталог через установленный Codex.")
    return list(dict.fromkeys(names))


def load_models(provider, base_url=""):
    """Загружает каталог выбранного сервиса; API-запрос выполняется только по кнопке UI."""
    if provider == "Codex CLI":
        return codex_models()
    # Каталог не требует выбора модели, но требует тех же адреса и ключа, что генерация.
    validate_settings(ModelSettings(provider, "catalog", base_url))
    key_name, default_url, _ = PROVIDERS[provider]
    headers = {}
    url = (base_url if provider == "Локальный API" else default_url).rstrip("/") + "/models"
    if provider == "Anthropic":
        headers = {"x-api-key": os.getenv(key_name, ""), "anthropic-version": "2023-06-01"}
        url += "?limit=100"
    else:
        headers = {"Authorization": "Bearer " + (os.getenv(key_name) or "local")}
    data = request_json(url, payload=None, headers=headers, timeout=10)
    try:
        items = data["data"]
        if not isinstance(items, list):
            raise ValueError
        names = [item["id"] for item in items if isinstance(item, dict)
                 and isinstance(item.get("id"), str) and item["id"].strip()]
    except (KeyError, TypeError, ValueError):
        raise ServiceError("Сервис вернул неожиданный формат списка моделей.") from None
    if provider == "OpenAI":
        names = [name for name in names if name.startswith(("gpt-", "o1", "o3", "o4"))
                 and not any(word in name for word in ("image", "audio", "realtime", "transcribe", "tts"))]
    elif provider == "Google Gemini":
        names = [name for name in names if "gemini" in name and "embedding" not in name]
    if not names:
        raise ServiceError("Сервис не вернул текстовых моделей. Проверьте доступ и адрес API.")
    return sorted(set(names))
