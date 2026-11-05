"""Обновляет схему в README средствами LangGraph без вызова модели и внешнего рендера."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm.providers import ModelSettings
from src.workflow import build_graph


START = "<!-- langgraph:start -->"
END = "<!-- langgraph:end -->"


def diagram():
    """Получает Mermaid из скомпилированного графа; узлы при этом не выполняются."""
    graph = build_graph(ModelSettings("Локальный API", "diagram", "http://localhost:1/v1"))
    return graph.get_graph().draw_mermaid()


def main():
    """Сохраняет исходник диаграммы и синхронизирует выделенный блок README."""
    source = diagram()
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1:
        raise SystemExit("В README должен быть один блок langgraph:start / langgraph:end.")
    before, remainder = text.split(START)
    _, after = remainder.split(END)
    updated = before + START + "\n```mermaid\n" + source.rstrip() + "\n```\n" + END + after
    (ROOT / "docs" / "workflow.mmd").write_text(source, encoding="utf-8")
    path.write_text(updated, encoding="utf-8")
    print("README.md и docs/workflow.mmd обновлены из настоящего графа LangGraph.")


if __name__ == "__main__":
    main()
