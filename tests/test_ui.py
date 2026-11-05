"""Проверяет интерфейс в памяти без сервера и обращений к моделям при наличии Streamlit."""

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import json


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit не установлен; зависимости не устанавливались")
class UITests(unittest.TestCase):
    """Проверяет начальное состояние и ошибку входа через штатный AppTest."""

    def setUp(self):
        """Изолирует интерфейсные проверки от настоящих ключей пользователя и сетевых каталогов."""
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("src.llm.model_catalog.load_models", return_value=["gpt-a", "gpt-b"])
    def test_catalog_auto_load_cache_and_refresh(self, catalog):
        """Загружает полный подставной каталог автоматически и повторяет запрос только по кнопке."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py"))
        app.session_state["provider"] = "OpenAI"
        app.run(timeout=5)
        self.assertFalse(app.exception)
        models = next(box for box in app.selectbox if box.label == "Название модели")
        self.assertEqual(models.options, ["gpt-a", "gpt-b"])
        catalog.assert_called_once_with("OpenAI", "")
        models.select("gpt-b")
        app.run(timeout=5)
        self.assertEqual(catalog.call_count, 1)
        self.assertEqual(next(box for box in app.selectbox if box.label == "Название модели").value, "gpt-b")
        next(button for button in app.button if button.label == "Обновить список моделей").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertEqual(catalog.call_count, 2)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("src.llm.model_catalog.load_models")
    def test_catalog_error_does_not_retry_on_every_rerun(self, catalog):
        """Ошибка остаётся видимой и не вызывает новый запрос при каждом изменении UI."""
        from streamlit.testing.v1 import AppTest
        from src.models import ServiceError

        catalog.side_effect = ServiceError("Каталог недоступен")
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py"))
        app.session_state["provider"] = "OpenAI"
        app.run(timeout=5)
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertEqual(catalog.call_count, 1)
        self.assertTrue(any("Каталог недоступен" in warning.value for warning in app.warning))
        next(button for button in app.button if button.label == "Обновить список моделей").click()
        app.run(timeout=5)
        self.assertEqual(catalog.call_count, 2)

    @patch("src.llm.model_catalog.load_models")
    def test_no_catalog_request_without_key(self, catalog):
        """Без доступа сохраняет подписанный список примеров и не выполняет сетевой запрос."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py"))
        app.session_state["provider"] = "OpenAI"
        app.run(timeout=5)
        self.assertFalse(app.exception)
        catalog.assert_not_called()

    def test_startup_and_default_enrichment(self):
        """Открытие приложения не требует ключа, модели или сетевого запроса."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        self.assertFalse(app.exception)
        self.assertEqual(next(box for box in app.selectbox if box.label == "Способ подключения").value, "Codex CLI")
        self.assertEqual(next(box for box in app.selectbox if box.label == "Сценарий").value, "conflict")
        self.assertTrue(app.checkbox[0].value)
        self.assertIn("МК110", app.text_area[0].value)
        self.assertTrue(any(box.label == "Название модели" for box in app.selectbox))
        self.assertFalse(any(field.label == "Название модели" for field in app.text_input))

    @patch("src.llm.model_catalog.codex_models", return_value=["codex-example"])
    def test_codex_model_is_dropdown(self, catalog):
        """Для Codex тоже предлагается выбор, а не обязательный ручной ввод."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        next(box for box in app.selectbox if box.label == "Способ подключения").select("Codex CLI")
        app.run(timeout=5)
        self.assertFalse(app.exception)
        models = next(box for box in app.selectbox if box.label == "Название модели")
        self.assertEqual(models.options, ["codex-example"])
        self.assertEqual(models.value, "codex-example")
        self.assertFalse(any(field.label == "Название модели" for field in app.text_input))

    def test_bad_json_shown_without_model(self):
        """Ошибка JSON отображается до проверки ключа и загрузки страницы."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        app.text_area[0].set_value("{")
        next(button for button in app.button if button.label == "Сформировать черновик").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertTrue(any("Некорректный JSON" in error.value for error in app.error))

    def test_conflict_preview_and_copy_to_editor(self):
        """Проверяет фактический конфликт во вкладке и перенос локального источника в редактор."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        next(box for box in app.selectbox if box.label == "Сценарий").select("conflict")
        app.run(timeout=5)
        next(button for button in app.button if button.label == "Проверить сценарий без модели").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["scenario_preview"][1]["status"], "awaiting_resolution")
        self.assertEqual(app.session_state["scenario_preview"][1]["attempts"], 0)
        app.session_state["workspace_tab"] = "Примеры сценариев"
        app.session_state["review_session"] = {"old": True}
        app.session_state["result_signature"] = "old"
        next(button for button in app.button if button.label == "Подставить в редактор").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertIn("demo://conflict", app.text_area[0].value)
        self.assertEqual(app.session_state["demo_scenario_id"], "conflict")
        self.assertEqual(app.session_state["workspace_tab"], "Карточка товара")
        self.assertTrue(any("подставлен в редактор" in message.value for message in app.success))
        self.assertNotIn("review_session", app.session_state)
        self.assertNotIn("result_signature", app.session_state)
        self.assertTrue(any("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ" in warning.value for warning in app.warning))
        for expander in app.expander:
            if expander.label == "Источники и дообогащение":
                self.assertFalse(expander.proto.expanded)
        next(button for button in app.button if button.label == "Подставить выбранный пример").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertNotIn("demo://", app.text_area[0].value)
        with self.assertRaises(KeyError):
            app.session_state["demo_scenario_id"]

    def test_scenario_conflict_can_be_resolved_in_its_tab(self):
        """Вкладка показывает варианты и сохраняет выбор в сценарии, не перезаписывая рабочий результат."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        original = {"status": "invalid_input", "error": "Предыдущий рабочий результат"}
        app.session_state["result"] = original
        next(box for box in app.selectbox if box.label == "Сценарий").select("conflict")
        app.run(timeout=5)
        next(button for button in app.button if button.label == "Проверить сценарий без модели").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        self.assertIsNone(app.radio[0].value)
        app.radio[0].set_value(1)
        next(button for button in app.button if button.label == "Применить выбор (без модели)").click()
        app.run(timeout=5)
        self.assertFalse(app.exception)
        result = app.session_state["scenario_preview"][1]
        self.assertEqual(result["facts"]["specs"]["Питание"], "220 В")
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(app.session_state["result"], original)

    def test_clean_result_requires_no_operator(self):
        """Карточка без расхождений готова без имени, комментария и кнопки подтверждения."""
        from streamlit.testing.v1 import AppTest
        from src.workflow import create_review_session
        from src.llm.providers import ModelSettings

        generator = Mock(return_value=json.dumps({
            "seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
            "search_queries": ["прибор", "выбор прибора", "заказать прибор"], "commercial": "Для задач предприятия.",
        }))
        session = create_review_session(ModelSettings("Локальный API", "test"), generator=generator)
        with patch("src.workflow.create_review_session", return_value=session):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
            app.checkbox[0].set_value(False)
            next(button for button in app.button if button.label == "Сформировать черновик").click()
            app.run(timeout=5)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["result"]["review"]["status"], "not_required")
            self.assertEqual(app.session_state["result"]["status"], "draft")
            self.assertFalse(app.radio)
            self.assertFalse(any(field.label == "Специалист (имя)" for field in app.text_input))
            self.assertEqual(generator.call_count, 1)

    def test_automatic_issues_do_not_create_operator_form(self):
        """Замечания автоматики доступны в подробностях и не превращаются в анкету оператору."""
        from streamlit.testing.v1 import AppTest
        from src.card.validation import validate_card

        card = {"seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
                "search_queries": ["прибор", "выбор прибора", "заказать прибор"], "commercial": "Питание 50 В."}
        facts = {"name": "Прибор", "manufacturer": "Завод", "specs": {"Питание": "24 В"},
                 "provenance": {"Питание": [{"source": "Паспорт", "excerpt": "Питание: 24 В"}]},
                 "descriptions": [], "missing": [], "conflicts": []}
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        app.session_state["result"] = {"status": "needs_review", "card": card, "facts": facts,
                                      "issues": validate_card(card, facts)}
        app.run(timeout=5)
        self.assertFalse(app.exception)
        text = "\n".join(item.value for item in app.markdown)
        code = "\n".join(item.value for item in app.code)
        self.assertNotIn("Вопрос специалисту:", text)
        self.assertFalse(app.radio)
        self.assertIn("Питание 50 В", text)
        for label in ("Замечания автоматической проверки", "Источники и дообогащение", "Скопировать или скачать результат"):
            self.assertFalse(next(expander for expander in app.expander if expander.label == label).proto.expanded)

    def test_conflict_has_separate_choice_and_applies_selected_value(self):
        """Оператор выбирает готовый вариант; этот выбор применяется перед единственным вызовом модели."""
        from streamlit.testing.v1 import AppTest
        from src.workflow import create_review_session
        from src.llm.providers import ModelSettings
        from src.sources.website import PageFacts

        url = "https://www.souz-pribor.ru/product/test/"
        raw = json.dumps({"name": "Прибор", "url": url,
                          "specs": {"Питание": "24 В", "Интерфейс": "RS-485", "Степень защиты": "IP20"}})
        generator = Mock(return_value=json.dumps({
            "seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
            "search_queries": ["прибор", "выбор прибора", "заказать прибор"], "commercial": "Для задач предприятия.",
        }))
        session = create_review_session(ModelSettings("Локальный API", "test"), generator=generator,
                                        fetcher=Mock(return_value=PageFacts(url, specs={"Питание": "220 В"})))
        with patch("src.workflow.create_review_session", return_value=session):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
            app.text_area[0].set_value(raw)
            next(button for button in app.button if button.label == "Сформировать черновик").click()
            app.run(timeout=5)
            self.assertFalse(app.exception)
            generator.assert_not_called()
            self.assertEqual(app.session_state["result"]["status"], "awaiting_resolution")
            self.assertIsNone(app.radio[0].value)
            app.radio[0].set_value(1)
            next(button for button in app.button if button.label == "Применить выбор и сформировать карточку").click()
            app.run(timeout=5)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["result"]["facts"]["specs"]["Питание"], "220 В")
            self.assertEqual(app.session_state["result"]["status"], "draft")
            self.assertEqual(generator.call_count, 1)
            self.assertFalse(app.radio)


if __name__ == "__main__":
    unittest.main()
