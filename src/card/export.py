"""Экспортирует карточку вместе с предупреждениями, чтобы не потерять ограничения."""

import json


STATUS = {
    "draft": "Черновик: формальные проверки пройдены, нужна проверка человеком",
    "needs_review": "Черновик не прошёл все проверки",
    "insufficient_data": "Недостаточно подтверждённых данных",
    "invalid_input": "Некорректные входные данные",
    "service_error": "Ошибка выбранного сервиса",
}


def report(state):
    """Отделяет переносимые результаты от внутренних объектов графа."""
    facts = state.get("facts", {})
    return {
        "status": state.get("status"), "provider": state.get("provider"),
        "model": state.get("model"), "card": state.get("card"),
        "characteristics": facts.get("specs", {}), "missing": facts.get("missing", []),
        "conflicts": facts.get("conflicts", []), "added_from_url": facts.get("added", []),
        "sources": facts.get("provenance", {}), "source_page": facts.get("source_page"),
        "warnings": state.get("warnings", []), "validation_issues": state.get("issues", []),
        "error": state.get("error", ""), "attempts": state.get("attempts", 0),
    }


def markdown(state):
    """Включает предупреждения и источники в копируемый текст, включая неудачные результаты."""
    data = report(state)
    lines = ["# Черновик карточки", "", STATUS.get(data["status"], "Не завершено"), ""]
    card = data["card"]
    if card:
        lines += ["## SEO-заголовок", "", card["seo_title"], "", "## Описание", "",
                  card["seo_description"], "", "## Для менеджера", "", card["commercial"], "",
                  "## Поисковые запросы", "", *["- " + q for q in card["search_queries"]], ""]
    lines += ["## Характеристики", ""]
    lines += [f"- {key}: {value}" for key, value in data["characteristics"].items()]
    for label, values in (("Уточнить", data["missing"]), ("Предупреждения", data["warnings"]),
                          ("Замечания проверки", data["validation_issues"])):
        if values:
            lines += ["", "## " + label, "", *["- " + value for value in values]]
    if data["conflicts"]:
        lines += ["", "## Конфликты — не использованы при генерации", ""]
        for conflict in data["conflicts"]:
            lines.append("- " + conflict["field"] + ": " + "; ".join(
                f"{v['value']} ({v['source']})" for v in conflict["values"]))
    if data["source_page"]:
        lines += ["", "Источник: " + data["source_page"]["url"]]
    if data["error"]:
        lines += ["", "Ошибка: " + data["error"]]
    return "\n".join(lines)


def json_report(state):
    """Сохраняет русский текст без экранирования для удобного копирования."""
    return json.dumps(report(state), ensure_ascii=False, indent=2)
