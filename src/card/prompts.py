"""Отделяет инструкции от фактов и ограничивает роль модели написанием черновика."""

import json
from pathlib import Path

from ..models import CARD_SCHEMA, ServiceError


PROMPTS_PATH = Path(__file__).resolve().parents[2] / "prompts.json"


def load_system_prompt():
    """Читает актуальные инструкции перед запросом и сообщает об ошибке файла в интерфейсе."""
    try:
        prompts = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ServiceError("Не удалось прочитать prompts.json. Проверьте наличие файла, кодировку UTF-8 и формат JSON.") from exc
    prompt = prompts.get("system_prompt") if isinstance(prompts, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ServiceError("В prompts.json поле system_prompt должно содержать непустой текст.")
    return prompt


def build_prompt(facts, issues=None):
    """Передаёт только допущенные факты; спорные значения и прошлые карточки не включает."""
    safe = {key: facts[key] for key in ("name", "manufacturer", "specs", "descriptions", "missing")}
    content = {"facts": safe, "output_schema": CARD_SCHEMA}
    if issues:
        content["corrections"] = issues
    return json.dumps(content, ensure_ascii=False)
