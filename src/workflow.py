"""Готовит карточку автоматически, запрашивая человека только при расхождении JSON и сайта."""

from typing import TypedDict
from dataclasses import asdict

from .card.facts import prepare_facts
from .card.extraction import extract_descriptions
from .card.review import human_review_node, validate_decision
from .card.review_guide import build_review_guide
from .models import CARD_SCHEMA, InputError, Product, ServiceError, decode_card, parse_product
from .card.prompts import SYSTEM_PROMPT, build_prompt
from .llm.providers import generate, validate_settings
from .card.validation import validate_card
from .sources.website import PageFacts, fetch_page


class State(TypedDict, total=False):
    """Хранит данные одного товара; история между запусками не переносится."""

    raw: str
    enrich: bool
    product: dict
    page: dict | None
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
    extracted: list[dict]
    review: dict


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
        return {"product": asdict(product), "steps": ["Проверка входа"]}

    def enrich(self, state):
        """Пробует дообогащение по умолчанию, сохраняя возможность работы без сайта."""
        warnings, page = [], None
        product = Product(**state["product"])
        if state.get("enrich", True):
            if product.url:
                try:
                    page = self.fetcher(product)
                except ServiceError as exc:
                    warnings.append("Дообогащение не выполнено: " + str(exc))
            else:
                warnings.append("URL не указан: дообогащение пропущено.")
        else:
            warnings.append("Дообогащение отключено пользователем.")
        return {"page": asdict(page) if page else None, "warnings": warnings,
                "steps": [*state["steps"], "Получение источника"]}

    def extract(self, state):
        """Извлекает только явно записанные значения с дословными фрагментами источников."""
        product, page = source_objects(state)
        return {"extracted": extract_descriptions(product, page),
                "steps": [*state["steps"], "Извлечение характеристик"]}

    def prepare(self, state):
        """Отделяет конфликты и решает, достаточно ли подтверждённых данных."""
        product, page = source_objects(state)
        facts = prepare_facts(product, page, extracted=state.get("extracted"))
        needs_choice = bool(build_review_guide({"facts": facts}))
        return {"facts": facts, "warnings": [*state["warnings"], *facts["warnings"]],
                "status": "awaiting_resolution" if needs_choice else ("pending" if facts["enough"] else "insufficient_data"),
                "review": {"status": "pending" if needs_choice else "not_required"},
                "steps": [*state["steps"], "Подготовка фактов"]}

    def generate(self, state):
        """Создаёт независимый запрос; при доработке передаёт замечания и те же факты."""
        updates = {"attempts": state.get("attempts", 0) + 1, "card": None,
                   "provider": self.settings.provider, "model": self.settings.model,
                   "steps": [*state["steps"], "Генерация"]}
        try:
            if self.generator is generate:
                validate_settings(self.settings)
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
        result = {"issues": issues, "status": "needs_review" if issues else "draft",
                  "steps": [*state["steps"], "Проверка результата"]}
        return result


def source_objects(state):
    """Восстанавливает объекты из простого состояния, которое безопасно сохраняется в памяти графа."""
    return Product(**state["product"]), PageFacts(**state["page"]) if state.get("page") else None


def build_graph(settings, *, generator=generate, fetcher=fetch_page, checkpointer=None):
    """Создаёт настоящий LangGraph; без установленных зависимостей запуск невозможен."""
    from langgraph.graph import END, START, StateGraph

    nodes = Nodes(settings, generator, fetcher)
    graph = StateGraph(State)
    for name in ("validate", "prepare", "generate", "check"):
        graph.add_node(name, getattr(nodes, name))
    graph.add_node("fetch_source", nodes.enrich)
    graph.add_node("extract_facts", nodes.extract)
    graph.add_node("human_review", human_review_node)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", lambda s: "stop" if s.get("error") else "next",
                                {"stop": END, "next": "fetch_source"})
    graph.add_edge("fetch_source", "extract_facts")
    graph.add_edge("extract_facts", "prepare")
    graph.add_conditional_edges("prepare", after_prepare,
                                {"stop": END, "next": "generate", "review": "human_review"})
    graph.add_conditional_edges("generate", lambda s: "stop" if s.get("error") else "next",
                                {"stop": END, "next": "check"})
    graph.add_conditional_edges("check", after_check, {"retry": "generate", "stop": END})
    graph.add_conditional_edges("human_review", lambda s: "next" if s["facts"]["enough"] else "stop",
                                {"next": "generate", "stop": END})
    return graph.compile(checkpointer=checkpointer)


def after_check(state):
    """Разрешает только одну доработку, включая случай неверного JSON модели."""
    return "retry" if state["issues"] and state["attempts"] < 2 else "stop"


def after_prepare(state):
    """Запрашивает выбор только при локальном расхождении с сайтом, до обращения к модели."""
    if build_review_guide(state):
        return "review"
    return "next" if state["facts"]["enough"] else "stop"


def create_review_session(settings, *, generator=generate, fetcher=fetch_page):
    """Сохраняет в памяти возможность продолжить генерацию после выбора спорных значений."""
    from langgraph.checkpoint.memory import InMemorySaver
    from uuid import uuid4

    return {"graph": build_graph(settings, generator=generator, fetcher=fetcher, checkpointer=InMemorySaver()),
            "config": {"configurable": {"thread_id": uuid4().hex}}}


def resume_review(session, state, payload):
    """Применяет ответы к ожидающим данным и продолжает генерацию с выбранными значениями."""
    from langgraph.types import Command
    from .models import InputError
    from .card.review import resolution_digest

    snapshot = session["graph"].get_state(session["config"])
    if snapshot.next != ("human_review",) or resolution_digest(state) != resolution_digest(snapshot.values):
        raise InputError("Данные изменились или выбор уже сохранён. Начните подготовку карточки заново.")
    decision = validate_decision(snapshot.values, payload)
    result = session["graph"].invoke(Command(resume=decision), session["config"])
    if state.get("demonstration"):
        result["demonstration"] = state["demonstration"]
        result["warnings"] = list(state.get("warnings", []))
    return result


def run(raw, settings, enrich=True, *, fetcher=fetch_page, session=None):
    """Запускает граф; недостаток данных обнаруживает без ключа, а доступ проверяет перед генерацией."""
    try:
        parse_product(raw)
    except InputError as exc:
        return {"status": "invalid_input", "error": str(exc), "steps": ["Проверка входа"]}
    graph = session["graph"] if session else build_graph(settings, fetcher=fetcher)
    return graph.invoke({"raw": raw, "enrich": enrich, "attempts": 0,
                         "issues": [], "warnings": [], "error": "", "card": None},
                        session["config"] if session else None)
