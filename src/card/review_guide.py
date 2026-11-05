"""Выделяет только реальные расхождения локальных данных со страницей товара."""

import hashlib
import json

from .normalization import comparable


def is_local(source):
    """Отличает входной JSON и его описание от сведений со страницы."""
    return source.startswith("Входной JSON")


def build_review_guide(state):
    """Создаёт один выбор на параметр, только когда локальное значение расходится с сайтом."""
    facts = state.get("facts", {})
    page_url = (facts.get("source_page") or {}).get("url")
    tasks = []
    for conflict in facts.get("conflicts", []):
        values = conflict["values"]
        local = [v for v in values if is_local(v["source"])]
        remote = [v for v in values if page_url and v["source"] == page_url]
        if not local or not remote:
            continue
        choices = []
        for value in local + remote:
            if not any(comparable(v.get("field", conflict["field"]), v["value"]) == comparable(value.get("field", conflict["field"]), value["value"])
                       and is_local(v["source"]) == is_local(value["source"]) for v in choices):
                choices.append(dict(value))
        content = json.dumps({"field": conflict["field"], "choices": choices}, sort_keys=True, ensure_ascii=False)
        tasks.append({"id": hashlib.sha256(content.encode()).hexdigest()[:16], "kind": "conflict",
                      "field": conflict["field"], "title": "Разные значения: " + conflict["field"],
                      "choices": choices, "sources": [{"field": conflict["field"], **v} for v in choices],
                      "locations": [{"section": "Локальные данные и сайт", "excerpt": conflict["field"]}],
                      "question": "Какое значение использовать в карточке?",
                      "action": "Выберите подтверждённое значение или «Пока неизвестно»."})
    return tasks
