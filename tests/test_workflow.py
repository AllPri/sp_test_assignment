"""Проверяет узлы и условия графа без модели; полный LangGraph — только если установлен."""

import importlib.util
import json
import unittest
from unittest.mock import Mock

from src.models import ServiceError
from src.llm.providers import ModelSettings
from src.workflow import Nodes, after_check, build_graph


RAW = json.dumps({"name": "Прибор", "manufacturer": "Завод",
                  "specs": {"Питание": "24 В", "Интерфейс": "RS-485"}}, ensure_ascii=False)
CARD = json.dumps({"seo_title": "Прибор", "seo_description": "Описание прибора. " * 55,
                   "search_queries": ["прибор", "купить прибор", "заказать прибор"],
                   "commercial": "Для задач предприятия."}, ensure_ascii=False)
SETTINGS = ModelSettings("Локальный API", "test-model", "http://localhost:11434/v1")


def prepared(nodes, raw=RAW, enrich=False):
    """Выполняет подготовительные узлы напрямую, чтобы не подменять библиотеку графа."""
    state = {"raw": raw, "enrich": enrich, "attempts": 0, "issues": [], "steps": []}
    state.update(nodes.validate(state))
    if not state.get("error"):
        state.update(nodes.enrich(state))
        state.update(nodes.prepare(state))
    return state


class NodeTests(unittest.TestCase):
    """Проверяет обработку отказов, ограничение доработки и независимость товаров."""

    def test_invalid_input_no_external_calls(self):
        """Ошибочный JSON заканчивает подготовку до загрузки страницы и модели."""
        generator, fetcher = Mock(), Mock()
        state = prepared(Nodes(SETTINGS, generator, fetcher), "{")
        self.assertEqual(state["status"], "invalid_input")
        generator.assert_not_called()
        fetcher.assert_not_called()

    def test_failed_enrichment_keeps_input(self):
        """Сбой сайта не мешает использовать достаточные исходные характеристики."""
        raw = json.dumps({**json.loads(RAW), "url": "https://www.souz-pribor.ru/product/a/"})
        fetcher = Mock(side_effect=ServiceError("Сайт недоступен"))
        state = prepared(Nodes(SETTINGS, Mock(), fetcher), raw, True)
        self.assertTrue(state["facts"]["enough"])
        self.assertIn("Сайт недоступен", state["warnings"][0])

    def test_retry_repairs_invalid_model_json(self):
        """После неверного JSON допускается один повтор с замечаниями."""
        generator = Mock(side_effect=["{", CARD])
        nodes = Nodes(SETTINGS, generator, Mock())
        state = prepared(nodes)
        state.update(nodes.generate(state))
        state.update(nodes.check(state))
        self.assertEqual(after_check(state), "retry")
        state.update(nodes.generate(state))
        state.update(nodes.check(state))
        self.assertEqual(state["status"], "draft")
        self.assertEqual(state["attempts"], 2)
        self.assertIn("corrections", generator.call_args.args[2])

    def test_retry_stops_after_second_failure(self):
        """Повторная неудача не скрывается за успешным статусом."""
        nodes = Nodes(SETTINGS, Mock(return_value="{"), Mock())
        state = prepared(nodes)
        for _ in range(2):
            state.update(nodes.generate(state))
            state.update(nodes.check(state))
        self.assertEqual(after_check(state), "stop")
        self.assertEqual(state["status"], "needs_review")
        self.assertIsNone(state["card"])

    def test_service_error_no_fallback(self):
        """Ошибка API завершает запрос, не вызывая другую модель или повтор."""
        generator = Mock(side_effect=ServiceError("HTTP 429"))
        nodes = Nodes(SETTINGS, generator, Mock())
        state = prepared(nodes)
        state.update(nodes.generate(state))
        self.assertEqual(state["status"], "service_error")
        self.assertEqual(generator.call_count, 1)

    def test_no_previous_card_in_next_product(self):
        """Один объект узлов не должен хранить историю предыдущей генерации."""
        generator = Mock(return_value=CARD)
        nodes = Nodes(SETTINGS, generator, Mock())
        for name in ("ТоварА", "ТоварБ"):
            state = prepared(nodes, json.dumps({**json.loads(RAW), "name": name}))
            nodes.generate(state)
        self.assertNotIn("ТоварА", generator.call_args.args[2])
        self.assertIn("ТоварБ", generator.call_args.args[2])


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "LangGraph не установлен; зависимости не устанавливались")
class GraphTests(unittest.TestCase):
    """Проверяет настоящие переходы LangGraph, когда пакет доступен в окружении."""

    def test_graph_success(self):
        """Компилирует граф и выполняет успешный путь с подставной моделью."""
        generator = Mock(return_value=CARD)
        result = build_graph(SETTINGS, generator=generator).invoke({"raw": RAW, "enrich": False})
        self.assertEqual(result["status"], "draft")
        self.assertEqual(generator.call_count, 1)

    def test_graph_retry_limit(self):
        """Проверяет ограничение повторов именно на рёбрах графа."""
        generator = Mock(return_value="{")
        result = build_graph(SETTINGS, generator=generator).invoke({"raw": RAW, "enrich": False})
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(generator.call_count, 2)

    def test_graph_insufficient_data(self):
        """Не обращается к модели при недостатке фактов."""
        generator = Mock()
        result = build_graph(SETTINGS, generator=generator).invoke({"raw": '{"name":"A"}', "enrich": False})
        self.assertEqual(result["status"], "insufficient_data")
        generator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
