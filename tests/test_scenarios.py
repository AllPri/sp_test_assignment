"""Проверяет воспроизводимость сценариев, отсутствие сети и честную маркировку экспорта."""

import importlib.util
import json
import unittest
from unittest.mock import Mock, patch

from src.card.export import json_report, markdown
from src.card.prompts import build_prompt
from src.demo.scenarios import label_result, load_scenarios, preview_scenario
from src.llm.providers import ModelSettings
from src.models import Product, ServiceError
from src.workflow import build_graph


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "LangGraph не установлен")
class ScenarioTests(unittest.TestCase):
    """Исполняет настоящую подготовку графа на локальных источниках."""

    def setUp(self):
        """Загружает независимые сценарии для каждой проверки."""
        self.scenarios = load_scenarios()

    @patch("src.transport.request_bytes", side_effect=AssertionError("Сетевой запрос запрещён"))
    def test_all_previews_without_network_or_model(self, request):
        """Все примеры завершают проверку до генерации и не требуют ключей."""
        statuses = {"insufficient": "insufficient_data", "invalid_json": "invalid_input", "conflict": "awaiting_resolution"}
        for key, scenario in self.scenarios.items():
            with self.subTest(scenario=key):
                state = preview_scenario(scenario)
                self.assertEqual(state["status"], statuses.get(key, "preview"))
                self.assertEqual(state["attempts"], 0)
                self.assertIsNone(state.get("card"))
                self.assertNotIn("Генерация", state["steps"])
                self.assertTrue(state["demonstration"]["preview"])
        request.assert_not_called()

    def test_conflict_excluded_from_model_input(self):
        """Показывает оба значения, но ни одно не допускает в данные генерации."""
        state = preview_scenario(self.scenarios["conflict"])
        facts = state["facts"]
        self.assertEqual(len(facts["conflicts"]), 1)
        self.assertEqual({v["value"] for v in facts["conflicts"][0]["values"]}, {"24 В", "220 В"})
        self.assertNotIn("Питание", facts["specs"])
        self.assertEqual(facts["specs"]["Интерфейс"], "RS-485")
        self.assertNotIn("24 В", build_prompt(facts))
        self.assertNotIn("220 В", build_prompt(facts))

    def test_empty_and_wrong_variant(self):
        """Пустое поле получает пометку, чужое исполнение не добавляет свойства."""
        empty = preview_scenario(self.scenarios["empty_field"])
        self.assertEqual(empty["facts"]["specs"]["Питание"], "данных нет")
        wrong = preview_scenario(self.scenarios["wrong_variant"])
        self.assertFalse(wrong["facts"]["added"])
        self.assertTrue(any("исполнение" in w for w in wrong["warnings"]))

    def test_unavailable_preserves_input(self):
        """Отказ локального источника оставляет возможность использовать исходные факты."""
        state = preview_scenario(self.scenarios["unavailable"])
        self.assertTrue(state["facts"]["enough"])
        self.assertTrue(any("недоступен" in w for w in state["warnings"]))

    def test_source_bound_to_selected_url(self):
        """Изменение URL не вызывает ни незаметную подмену, ни обращение к интернету."""
        with self.assertRaisesRegex(ServiceError, "URL"):
            self.scenarios["conflict"].fetch(Product("ДЕМО-24", url="https://example.com"))

    def test_generation_and_exports_keep_demo_label(self):
        """Сценарий использует общий граф и сохраняет предупреждение в обоих форматах."""
        scenario = self.scenarios["complete"]
        generator = Mock(return_value=json.dumps({
            "seo_title": "ДЕМО-24", "seo_description": "Описание учебного прибора. " * 40,
            "search_queries": ["учебный прибор", "прибор для сбора показаний", "прибор диспетчеризации"],
            "commercial": "Для учебной демонстрации сбора показаний.",
        }, ensure_ascii=False))
        graph = build_graph(ModelSettings("Локальный API", "test"), generator=generator, fetcher=scenario.fetch)
        state = graph.invoke({"raw": scenario.raw, "enrich": True})
        state = label_result(state, scenario)
        self.assertEqual(state["status"], "draft")
        self.assertEqual(generator.call_count, 1)
        self.assertIn("IP20", state["facts"]["specs"].values())
        self.assertFalse(state["demonstration"]["preview"])
        for exported in (json_report(state), markdown(state)):
            self.assertIn("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ", exported)
            self.assertIn("demo://complete", exported)


if __name__ == "__main__":
    unittest.main()
