"""Запрашивает выбор только при расхождении JSON и сайта и применяет его перед генерацией."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from ..models import InputError
from .facts import assess_content
from .normalization import field_key
from .review_guide import build_review_guide, is_local


def resolution_digest(state):
    """Привязывает выбор к конкретным входным данным и обнаруженным расхождениям."""
    data = {"product": state.get("product"), "facts": state.get("facts")}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_decision(state, payload):
    """Требует явного ответа на каждый пункт и не принимает придуманные значения."""
    tasks = build_review_guide(state)
    if not tasks or not isinstance(payload, dict) or not isinstance(payload.get("choices"), dict):
        raise InputError("Нет расхождений для выбора или не переданы ответы.")
    answers = payload["choices"]
    if set(answers) != {task["id"] for task in tasks}:
        raise InputError("Выберите ответ для каждого параметра.")
    for task in tasks:
        index = answers[task["id"]]
        if type(index) is not int or not -1 <= index < len(task["choices"]):
            raise InputError(f"Выберите значение для «{task['field']}» или «Пока неизвестно».")
    return {"choices": dict(answers)}


def apply_choices(state, payload):
    """Добавляет выбранные факты с доказательствами; неизвестные оставляет без технического значения."""
    tasks = build_review_guide(state)
    facts = deepcopy(state["facts"])
    resolved = []
    fields = {field_key(task["field"]) for task in tasks}
    facts["missing"] = [m for m in facts.get("missing", [])
                        if field_key(m.split(" — ")[0]) not in fields
                        and m not in ("Подтверждённое описание назначения", "Ключевые технические характеристики")]
    for task in tasks:
        index = payload["choices"][task["id"]]
        selected = task["choices"][index] if index >= 0 else None
        value = selected["value"] if selected else "данных нет"
        selected_field = selected.get("field", task["field"]) if selected else task["field"]
        facts["specs"][selected_field] = value
        if selected:
            facts["provenance"][selected_field] = [{"source": selected["source"],
                                                    "excerpt": selected.get("excerpt", task["field"] + ": " + value)}]
            if not is_local(selected["source"]):
                facts["added"].append({"field": selected_field, "value": value, "source": selected["source"]})
        else:
            facts["missing"].append(task["field"])
        resolved.append({"field": task["field"], "value": value,
                         "selected_field": selected_field,
                         "source": selected["source"] if selected else "Не определено",
                         "choice": index, "candidates": task["choices"]})
    facts["conflicts"] = [c for c in facts["conflicts"] if field_key(c["field"]) not in fields]
    missing, enough = assess_content(facts["specs"], facts["descriptions"])
    facts["missing"] = list(dict.fromkeys([*facts["missing"], *missing]))
    facts["enough"] = enough
    review = {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat(),
              "source_sha256": resolution_digest(state), "resolutions": resolved}
    return {"facts": facts, "review": review, "status": "pending" if enough else "insufficient_data",
            "steps": [*state["steps"], "Выбор значений при расхождении"]}


def human_review_node(state):
    """Приостанавливает граф до выбора значений; модель вызывается только после ответа человека."""
    from langgraph.types import interrupt

    payload = interrupt({"message": "Выберите значения при расхождении данных", "review_tasks": build_review_guide(state)})
    return apply_choices(state, validate_decision(state, payload))
