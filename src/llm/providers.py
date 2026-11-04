"""Подключает выбранный в UI сервис без автоматического переключения провайдера."""

from dataclasses import dataclass
import os
from urllib.parse import urlsplit

from ..models import ServiceError
from ..transport import request_json


PROVIDERS = {
    "OpenAI": ("OPENAI_API_KEY", "https://api.openai.com/v1", ["gpt-4.1-mini", "gpt-4.1"]),
    "Anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", ["claude-sonnet-4-5"]),
    "Google Gemini": (
        "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai",
        ["gemini-2.5-flash"],
    ),
    "Локальный API": ("LOCAL_MODEL_API_KEY", "http://127.0.0.1:11434/v1", []),
    "Codex CLI": ("", "", []),
}


@dataclass(frozen=True)
class ModelSettings:
    """Описывает один выбранный способ генерации; секреты в объект не помещаются."""

    provider: str
    model: str
    base_url: str = ""
    timeout: int = 90


def validate_settings(settings):
    """Проверяет доступные локально настройки до загрузки страницы и обращения к модели."""
    if settings.provider not in PROVIDERS:
        raise ServiceError("Выбран неизвестный провайдер.")
    if not settings.model.strip() or len(settings.model) > 150:
        raise ServiceError("Укажите название модели длиной до 150 символов.")
    if settings.provider == "Codex CLI":
        from shutil import which
        if which("codex") is None:
            raise ServiceError("Codex CLI не установлен или отсутствует в PATH.")
        return
    key_name = PROVIDERS[settings.provider][0]
    if settings.provider != "Локальный API" and not os.getenv(key_name):
        raise ServiceError(f"Добавьте {key_name} в .env и повторите запуск.")
    if settings.provider == "Локальный API":
        try:
            parsed = urlsplit(settings.base_url)
            parsed.port
        except ValueError:
            raise ServiceError("Некорректный адрес или порт локального API.") from None
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ServiceError("Укажите HTTP(S)-адрес локального API, заканчивающийся на /v1.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ServiceError("Адрес API не должен содержать пароль, параметры или фрагмент.")


def generate(settings, system, prompt, schema):
    """Отправляет независимый запрос с явным выбором модели и общей схемой результата."""
    validate_settings(settings)
    if settings.provider == "Codex CLI":
        from .codex_provider import generate_codex
        return generate_codex(settings, system, prompt, schema)
    key_name, default_url, _ = PROVIDERS[settings.provider]
    key = os.getenv(key_name, "")
    headers = {"Content-Type": "application/json"}
    if settings.provider == "Anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        payload = {
            "model": settings.model, "max_tokens": 2500, "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        url = default_url + "/messages"
    else:
        headers["Authorization"] = "Bearer " + (key or "local")
        payload = {
            "model": settings.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        # Локальный сервер может не поддерживать JSON Schema: формат задаёт промпт.
        if settings.provider != "Локальный API":
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "product_card", "strict": True, "schema": schema,
            }}
        url = (settings.base_url if settings.provider == "Локальный API" else default_url).rstrip("/")
        url += "/chat/completions"
    result = request_json(url, payload=payload, headers=headers, timeout=settings.timeout)
    try:
        if settings.provider == "Anthropic":
            return "\n".join(part["text"] for part in result["content"] if part.get("type") == "text")
        return result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ServiceError("Неожиданный формат ответа API. Проверьте совместимость модели.") from None
