"""Экспортирует карточку вместе с предупреждениями, чтобы не потерять ограничения."""

import json

from .review_guide import build_review_guide


STATUS = {
    "draft": "Черновик готов: автоматические проверки пройдены",
    "needs_review": "Автоматическая доработка не устранила все замечания",
    "awaiting_resolution": "Выберите значения при расхождении локальных данных с сайтом",
    "insufficient_data": "Недостаточно подтверждённых данных",
    "invalid_input": "Некорректные входные данные",
    "service_error": "Ошибка выбранного сервиса",
    "preview": "Проверка данных завершена; генерация модели не запускалась",
    "approved": "Карточка подтверждена специалистом; автоматические замечания сохранены",
    "rejected": "Карточка отклонена специалистом",
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
        "demonstration": state.get("demonstration"),
        "extracted_characteristics": facts.get("extracted", []),
        "human_review": state.get("review", {"status": "not_reviewed"}),
        "review_tasks": build_review_guide(state),
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
    review = data["human_review"]
    if review["status"] not in ("not_reviewed", "not_required"):
        lines += ["", "## Выбор значений при расхождении", "", "Статус: " + review["status"]]
    if review.get("resolved_at"):
        lines += ["Дата: " + review["resolved_at"]]
        lines += [f"- {r['field']}: {r['value']} ({r['source']})" for r in review.get("resolutions", [])]
    if review.get("reviewer"):
        lines += ["Специалист: " + review["reviewer"], "Дата: " + review["reviewed_at"],
                  "Комментарий: " + review.get("comment", "")]
    if data["review_tasks"]:
        lines += ["", "## Расхождения между локальными данными и сайтом", ""]
        for index, task in enumerate(data["review_tasks"], 1):
            lines += [f"{index}. {task['title']}", "Вопрос: " + task["question"]]
            lines += ["Где: " + item["section"] + " — " + item["excerpt"] for item in task["locations"]]
            lines += ["Источник: " + item.get("field", "") + " = " + item.get("value", "")
                      + " (" + item.get("source", "") + ")" for item in task["sources"]]
            lines += ["Действие: " + task["action"], ""]
    return "\n".join(lines)


def json_report(state):
    """Сохраняет русский текст без экранирования для удобного копирования."""
    return json.dumps(report(state), ensure_ascii=False, indent=2)
