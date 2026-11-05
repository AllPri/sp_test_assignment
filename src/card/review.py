"""Приостанавливает граф для ручного решения и сохраняет его отдельно от автоматических проверок."""

from datetime import datetime, timezone
import hashlib
import json

from ..models import InputError


def card_digest(state):
    """Привязывает решение специалиста к конкретным текстам и характеристикам."""
    content = {"card": state.get("card"), "specs": state.get("facts", {}).get("specs", {})}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_decision(state, payload):
    """Не допускает анонимного решения и молчаливого подтверждения карточки с замечаниями."""
    if not state.get("card"):
        raise InputError("Нет сформированной карточки для ручной проверки.")
    if not isinstance(payload, dict) or payload.get("decision") not in ("approve", "reject"):
        raise InputError("Выберите подтверждение или отклонение карточки.")
    for name in ("reviewer", "comment"):
        if not isinstance(payload.get(name, ""), str):
            raise InputError("Имя специалиста и комментарий должны быть текстом.")
    reviewer, comment = payload.get("reviewer", "").strip(), payload.get("comment", "").strip()
    if not reviewer or len(reviewer) > 120 or len(comment) > 2000:
        raise InputError("Укажите специалиста (до 120 символов); комментарий — до 2000 символов.")
    concerns = bool(state.get("issues") or state.get("facts", {}).get("conflicts"))
    if payload["decision"] == "reject" and not comment:
        raise InputError("Укажите причину отклонения.")
    if payload["decision"] == "approve" and concerns:
        if not comment or payload.get("acknowledge_issues") is not True:
            raise InputError("Изучите замечания и конфликты, подтвердите это и поясните решение.")
    return {"decision": payload["decision"], "reviewer": reviewer, "comment": comment,
            "acknowledge_issues": payload.get("acknowledge_issues") is True}


def human_review_node(state):
    """Ожидает ввод через interrupt; продолжение Command не вызывает модель повторно."""
    from langgraph.types import interrupt

    payload = interrupt({"message": "Требуется ручная проверка специалистом",
                         "automatic_status": state["status"], "issues": state.get("issues", []),
                         "conflicts": state.get("facts", {}).get("conflicts", [])})
    decision = validate_decision(state, payload)
    review = {**decision, "status": "approved" if decision["decision"] == "approve" else "rejected",
              "reviewed_at": datetime.now(timezone.utc).isoformat(), "card_sha256": card_digest(state),
              "automatic_status": state["status"], "automatic_issues": list(state.get("issues", []))}
    return {"review": review, "status": review["status"],
            "steps": [*state["steps"], "Ручная проверка специалистом"]}
