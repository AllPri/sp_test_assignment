"""Явно запускает реальные проверки через выбранную модель Codex и сохраняет результаты."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.card.export import json_report, markdown
from src.demo.scenarios import label_result, load_scenarios
from src.llm.providers import ModelSettings
from src.models import ServiceError
from src.workflow import run


def cases():
    """Задаёт два реальных товара, семь сценариев и извлечение из описания без подмены модели."""
    for name in ("mk110", "pm01"):
        yield name, (ROOT / "examples" / (name + ".json")).read_text(encoding="utf-8"), True, None
    for key, scenario in load_scenarios().items():
        yield key, scenario.raw, scenario.enrich, scenario
    from src.demo.scenarios import Scenario
    raw = json.dumps({"name": "ТЕСТ-24", "manufacturer": "Учебный завод",
                      "description": "Учебный прибор предназначен для сбора показаний и передачи данных в систему диспетчеризации. Питание 24 В; интерфейс RS-485; степень защиты IP20."}, ensure_ascii=False)
    scenario = Scenario("description_only", "Характеристики только в описании", "", "", raw, False)
    yield scenario.id, raw, False, scenario


def case_passed(name, state):
    """Проверяет контракт сценария; недостаточный объём текста допустим только с явным статусом проверки."""
    if name == "conflict":
        return (state["status"] == "awaiting_resolution" and state.get("attempts", 0) == 0
                and bool(state.get("facts", {}).get("conflicts")))
    if name == "insufficient":
        return state["status"] == "insufficient_data" and state.get("attempts", 0) == 0
    if name == "invalid_json":
        return state["status"] == "invalid_input" and state.get("attempts", 0) == 0
    if state["status"] != "draft":
        acceptable = (name in ("conflict", "wrong_variant", "unavailable", "empty_field")
                      and state["status"] == "needs_review" and bool(state.get("card"))
                      and all(issue.startswith("Описание:") for issue in state.get("issues", [])))
        if not acceptable:
            return False
    facts = state.get("facts", {})
    if name == "conflict":
        return bool(facts.get("conflicts")) and "Питание" not in facts.get("specs", {})
    if name == "empty_field":
        return facts.get("specs", {}).get("Питание") == "данных нет"
    if name == "wrong_variant":
        return not facts.get("added") and any("исполнение" in w for w in state.get("warnings", []))
    if name == "unavailable":
        return any("недоступен" in w for w in state.get("warnings", []))
    return True


def main():
    """Ограничивает время каждого обращения и сохраняет также неудачные результаты для разбора."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Модель из вашего каталога Codex")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / "results")
    parser.add_argument("--case", action="append", help="Проверить только выбранный случай; можно указать несколько раз")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = ModelSettings("Codex CLI", args.model, timeout=args.timeout)
    selected = [case for case in cases() if not args.case or case[0] in args.case]
    if args.case and set(args.case) - {case[0] for case in selected}:
        parser.error("Неизвестное имя случая")
    summary = {"started_at": datetime.now(timezone.utc).isoformat(), "model": args.model, "cases": []}
    previous = args.output / "summary.json"
    if args.case and previous.exists():
        summary = json.loads(previous.read_text(encoding="utf-8"))
    current = []
    for name, raw, enrich, scenario in selected:
        started = time.monotonic()
        try:
            state = run(raw, settings, enrich, **({"fetcher": scenario.fetch} if scenario else {}))
        except ServiceError as exc:
            state = {"status": "service_error", "error": str(exc), "provider": settings.provider, "model": settings.model}
        if scenario:
            state = label_result(state, scenario)
        (args.output / (name + ".json")).write_text(json_report(state), encoding="utf-8")
        (args.output / (name + ".md")).write_text(markdown(state), encoding="utf-8")
        item = {"name": name, "status": state["status"], "attempts": state.get("attempts", 0),
                "seconds": round(time.monotonic() - started, 2), "issues": state.get("issues", []),
                "error": state.get("error", ""), "conflicts": len(state.get("facts", {}).get("conflicts", [])),
                "checks_passed": case_passed(name, state)}
        summary["cases"] = [old for old in summary["cases"] if old["name"] != name] + [item]
        summary.setdefault("history", []).append({**item, "at": datetime.now(timezone.utc).isoformat(), "model": args.model})
        current.append(item)
        (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(item, ensure_ascii=False), flush=True)
    if any(not item["checks_passed"] for item in current):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
