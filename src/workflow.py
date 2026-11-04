"""Собирает расширяемый граф с одной доработкой и отдельными состояниями ошибок."""

from typing import TypedDict

from .card.facts import prepare_facts
from .models import CARD_SCHEMA, InputError, ServiceError, decode_card, parse_product
from .card.prompts import SYSTEM_PROMPT, build_prompt
from .llm.providers import generate, validate_settings
from .card.validation import validate_card
from .sources.website import fetch_page


class State(TypedDict, total=False):
    """Хранит данные одного товара; история между запусками не переносится."""

    raw: str
    enrich: bool
    product: object
    page: object
    facts: dict
    card: dict | None
    issues: list[str]
    warnings: list[str]
    attempts: int
    error: str
    status: str
    steps: list[str]
    provider: str
    model: str


class Nodes:
    """Получает заменяемые зависимости для проверки без API и сетевых запросов."""

    def __init__(self, settings, generator=generate, fetcher=fetch_page):
        """Закрепляет выбранную модель за одним запуском графа."""
        self.settings, self.generator, self.fetcher = settings, generator, fetcher

    def validate(self, state):
        """Отклоняет неверный JSON до любых внешних действий."""
        try:
            product = parse_product(state["raw"])
        except InputError as exc:
            return {"error": str(exc), "status": "invalid_input", "steps": ["Проверка входа"]}
        return {"product": product, "steps": ["Проверка входа"]}

    def enrich(self, state):
        """Пробует дообогащение по умолчанию, сохраняя возможность работы без сайта."""
        warnings, page = [], None
        if state.get("enrich", True):
            if state["product"].url:
                try:
                    page = self.fetcher(state["product"])
                except ServiceError as exc:
                    warnings.append("Дообогащение не выполнено: " + str(exc))
            else:
                warnings.append("URL не указан: дообогащение пропущено.")
        else:
            warnings.append("Дообогащение отключено пользователем.")
        return {"page": page, "warnings": warnings,
                "steps": [*state["steps"], "Получение источника"]}

    def prepare(self, state):
        """Отделяет конфликты и решает, достаточно ли подтверждённых данных."""
        facts = prepare_facts(state["product"], state.get("page"))
        return {"facts": facts, "warnings": [*state["warnings"], *facts["warnings"]],
                "status": "pending" if facts["enough"] else "insufficient_data",
                "steps": [*state["steps"], "Подготовка фактов"]}

    def generate(self, state):
        """Создаёт независимый запрос; при доработке передаёт замечания и те же факты."""
        updates = {"attempts": state.get("attempts", 0) + 1, "card": None,
                   "provider": self.settings.provider, "model": self.settings.model,
                   "steps": [*state["steps"], "Генерация"]}
        try:
            raw = self.generator(
                self.settings, SYSTEM_PROMPT, build_prompt(state["facts"], state.get("issues")), CARD_SCHEMA,
            )
            updates["card"] = decode_card(raw)
            updates["issues"] = []
        except ValueError as exc:
            updates["issues"] = [str(exc)]
        except ServiceError as exc:
            updates.update(error=str(exc), status="service_error")
        return updates

    def check(self, state):
        """Не помечает неудачную вторую попытку как успешную карточку."""
        issues = validate_card(state["card"], state["facts"]) if state.get("card") else state["issues"]
        return {"issues": issues, "status": "needs_review" if issues else "draft",
                "steps": [*state["steps"], "Проверка результата"]}


def build_graph(settings, *, generator=generate, fetcher=fetch_page):
    """Создаёт настоящий LangGraph; без установленных зависимостей запуск невозможен."""
    from langgraph.graph import END, START, StateGraph

    nodes = Nodes(settings, generator, fetcher)
    graph = StateGraph(State)
    for name in ("validate", "prepare", "generate", "check"):
        graph.add_node(name, getattr(nodes, name))
    graph.add_node("fetch_source", nodes.enrich)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", lambda s: "stop" if s.get("error") else "next",
                                {"stop": END, "next": "fetch_source"})
    graph.add_edge("fetch_source", "prepare")
    graph.add_conditional_edges("prepare", lambda s: "next" if s["facts"]["enough"] else "stop",
                                {"stop": END, "next": "generate"})
    graph.add_conditional_edges("generate", lambda s: "stop" if s.get("error") else "next",
                                {"stop": END, "next": "check"})
    graph.add_conditional_edges("check", after_check, {"retry": "generate", "stop": END})
    return graph.compile()


def after_check(state):
    """Разрешает только одну доработку, включая случай неверного JSON модели."""
    return "retry" if state["issues"] and state["attempts"] < 2 else "stop"


def run(raw, settings, enrich=True):
    """Запускает граф без сохранения истории; доступ к провайдеру проверяет до сети."""
    try:
        parse_product(raw)
    except InputError as exc:
        return {"status": "invalid_input", "error": str(exc), "steps": ["Проверка входа"]}
    validate_settings(settings)
    graph = build_graph(settings)
    return graph.invoke({"raw": raw, "enrich": enrich, "attempts": 0,
                         "issues": [], "warnings": [], "error": "", "card": None})
