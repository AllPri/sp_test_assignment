"""Проводит демонстрационные данные через общий граф без обращений к сайту."""

from dataclasses import dataclass
import json
from pathlib import Path

from ..llm.providers import ModelSettings
from ..models import ServiceError
from ..sources.website import parse_page
from ..workflow import build_graph


FOLDER = Path(__file__).resolve().parents[2] / "examples" / "scenarios"


@dataclass(frozen=True)
class Scenario:
    """Описывает вход, ожидаемую реакцию и локальный источник одного сценария."""

    id: str
    title: str
    explanation: str
    expected: str
    raw: str
    enrich: bool
    source_html: str = ""
    source_url: str = ""
    source_error: str = ""

    def fetch(self, product):
        """Подставляет сохранённый HTML в настоящий разборщик, не делая HTTP-запросов."""
        if not self.source_url or product.url != self.source_url:
            raise ServiceError("URL не соответствует демонстрационному источнику выбранного сценария.")
        if self.source_error:
            raise ServiceError(self.source_error)
        html = (FOLDER / self.source_html).read_text(encoding="utf-8")
        page = parse_page(html, product)
        page.warnings.insert(0, "Демонстрационный источник: локальный HTML, а не страница действительного товара.")
        return page


def load_scenarios():
    """Читает фиксированный каталог; JSON каждого товара остаётся доступен в редакторе."""
    entries = json.loads((FOLDER / "catalog.json").read_text(encoding="utf-8"))
    scenarios = {}
    for entry in entries:
        entry = dict(entry)
        product = entry.pop("product", None)
        if product is not None:
            entry["raw"] = json.dumps(product, ensure_ascii=False, indent=2)
        scenario = Scenario(**entry)
        scenarios[scenario.id] = scenario
    return scenarios


def label_result(state, scenario, *, preview=False):
    """Сохраняет пометку демонстрации также в предупреждениях и экспортируемом результате."""
    state["demonstration"] = {"scenario": scenario.title, "preview": preview, "source": "local_fixture"}
    state["warnings"] = [
        "ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ. Сценарий: " + scenario.title,
        *state.get("warnings", []),
    ]
    return state


def forbid_generation(*args, **kwargs):
    """Защищает проверку сценария от случайного перехода к генерации."""
    raise RuntimeError("Проверка сценария не должна вызывать модель.")


def preview_scenario(scenario):
    """Выполняет тот же граф до генерации: ключи, модель и доступ к интернету не нужны."""
    settings = ModelSettings("Локальный API", "preview", "http://localhost:1/v1")
    graph = build_graph(settings, generator=forbid_generation, fetcher=scenario.fetch)
    state = graph.invoke(
        {"raw": scenario.raw, "enrich": scenario.enrich, "attempts": 0,
         "issues": [], "warnings": [], "error": "", "card": None},
        interrupt_before=["generate"],
    )
    if state.get("status") == "pending":
        state["status"] = "preview"
    return label_result(state, scenario, preview=True)
