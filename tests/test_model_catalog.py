"""Проверяет каталоги моделей без сетевых запросов и запуска CLI."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.llm.model_catalog import codex_models, load_models
from src.models import ServiceError


class CatalogTests(unittest.TestCase):
    """Проверяет пригодность списков для выбора и изоляцию провайдеров."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_openai_filters_non_text_and_deduplicates(self, request):
        """Исключает модели других задач, не показывая повторяющиеся названия."""
        request.return_value = {"data": [{"id": name} for name in (
            "gpt-text", "gpt-text", "gpt-image-1", "gpt-audio", "whisper-1", "o3",
        )]}
        self.assertEqual(load_models("OpenAI"), ["gpt-text", "o3"])
        self.assertEqual(request.call_args.args[0], "https://api.openai.com/v1/models")
        self.assertIsNone(request.call_args.kwargs["payload"])

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_local_catalog_uses_selected_address(self, request):
        """Загружает имена, установленные именно на выбранном локальном сервере."""
        request.return_value = {"data": [{"id": "my-model:latest"}]}
        self.assertEqual(load_models("Локальный API", "http://localhost:8080/v1/"), ["my-model:latest"])
        self.assertEqual(request.call_args.args[0], "http://localhost:8080/v1/models")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_anthropic_authorization(self, request):
        """У Claude используется собственный заголовок авторизации каталога."""
        request.return_value = {"data": [{"id": "claude-example"}]}
        self.assertEqual(load_models("Anthropic"), ["claude-example"])
        self.assertEqual(request.call_args.kwargs["headers"]["x-api-key"], "test-key")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_gemini_filters_embedding(self, request):
        """В списке генерации не показываются модели векторизации."""
        request.return_value = {"data": [{"id": "gemini-text"}, {"id": "gemini-embedding-001"}]}
        self.assertEqual(load_models("Google Gemini"), ["gemini-text"])

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_missing_key_no_network(self, request):
        """Не обращается к провайдеру, если его ключ не настроен."""
        with self.assertRaisesRegex(ServiceError, "OPENAI_API_KEY"):
            load_models("OpenAI")
        request.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.llm.model_catalog.request_json")
    def test_bad_or_empty_catalog(self, request):
        """Пустой или повреждённый каталог даёт понятную ошибку вместо поля ввода."""
        for data in ([], {}, {"data": {}}, {"data": []}, {"data": [{"id": None}]}):
            with self.subTest(data=data), self.assertRaises(ServiceError):
                request.return_value = data
                load_models("Локальный API", "http://localhost:8080/v1")

    def test_codex_only_visible_names(self):
        """Читает только видимые имена, не скрытые служебные модели и не инструкции."""
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_HOME": directory}):
            Path(directory, "models_cache.json").write_text(json.dumps({"models": [
                {"slug": "visible-model", "visibility": "list"},
                {"slug": "internal-model", "visibility": "hide"},
            ]}))
            self.assertEqual(codex_models(), ["visible-model"])

    def test_codex_missing_or_invalid_cache(self):
        """Не заменяет неизвестный каталог Codex выдуманными именами."""
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEX_HOME": directory}):
            with self.assertRaisesRegex(ServiceError, "Codex"):
                codex_models()
            Path(directory, "models_cache.json").write_text("{")
            with self.assertRaisesRegex(ServiceError, "Codex"):
                codex_models()


if __name__ == "__main__":
    unittest.main()
