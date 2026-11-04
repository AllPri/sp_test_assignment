"""Проверяет интерфейс в памяти без сервера и обращений к моделям при наличии Streamlit."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit не установлен; зависимости не устанавливались")
class UITests(unittest.TestCase):
    """Проверяет начальное состояние и ошибку входа через штатный AppTest."""

    def test_startup_and_default_enrichment(self):
        """Открытие приложения не требует ключа, модели или сетевого запроса."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui.py")).run(timeout=5)
        self.assertFalse(app.exception)
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


if __name__ == "__main__":
    unittest.main()
