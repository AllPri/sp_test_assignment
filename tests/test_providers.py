"""Проверяет запросы и ошибки подключений без сети, ключей и запуска Codex."""

from email.message import Message
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from src.llm.codex_provider import generate_codex
from src.models import CARD_SCHEMA, ServiceError
from src.llm.providers import ModelSettings, generate
from src.transport import request_bytes


class ProviderTests(unittest.TestCase):
    """Проверяет, что настройки UI определяют единственный фактический запрос."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}, clear=True)
    @patch("src.llm.providers.request_json")
    def test_openai_schema_and_model(self, request):
        """Выбор модели и схема передаются провайдеру без изменения."""
        request.return_value = {"choices": [{"message": {"content": "{}"}}]}
        self.assertEqual(generate(ModelSettings("OpenAI", "chosen-model"), "system", "prompt", CARD_SCHEMA), "{}")
        self.assertEqual(request.call_args.kwargs["payload"]["model"], "chosen-model")
        self.assertEqual(request.call_args.kwargs["payload"]["response_format"]["type"], "json_schema")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret"}, clear=True)
    @patch("src.llm.providers.request_json")
    def test_anthropic_native_format(self, request):
        """Anthropic получает собственный формат API и отдельную системную инструкцию."""
        request.return_value = {"content": [{"type": "text", "text": "{}"}]}
        self.assertEqual(generate(ModelSettings("Anthropic", "chosen"), "system", "prompt", CARD_SCHEMA), "{}")
        self.assertEqual(request.call_args.kwargs["payload"]["system"], "system")
        self.assertTrue(request.call_args.args[0].endswith("/messages"))

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.llm.providers.request_json")
    def test_missing_api_key_no_request(self, request):
        """Отсутствующий ключ не приводит к запросу или переключению на локальный API."""
        with self.assertRaisesRegex(ServiceError, "GEMINI_API_KEY"):
            generate(ModelSettings("Google Gemini", "model"), "s", "p", CARD_SCHEMA)
        request.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.llm.providers.request_json")
    def test_local_without_key_or_schema_requirement(self, request):
        """Для локального совместимого сервера допускается отсутствие ключа и JSON Schema."""
        request.return_value = {"choices": [{"message": {"content": "{}"}}]}
        generate(ModelSettings("Локальный API", "local", "http://localhost:8080/v1"), "s", "p", CARD_SCHEMA)
        self.assertEqual(request.call_args.args[0], "http://localhost:8080/v1/chat/completions")
        self.assertNotIn("response_format", request.call_args.kwargs["payload"])


class TransportTests(unittest.TestCase):
    """Проверяет понятные ошибки и отсутствие секретов из ответа в сообщениях."""

    @patch("src.transport.build_opener")
    def test_http_error_sanitized(self, opener):
        """Текст исключения сервера может содержать секреты и не должен отображаться."""
        for code in (401, 403, 429, 500):
            opener.return_value.open.side_effect = HTTPError("https://api", code, "secret-key", Message(), None)
            with self.subTest(code=code), self.assertRaises(ServiceError) as caught:
                request_bytes("https://api")
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn("secret-key", str(caught.exception))

    @patch("src.transport.build_opener")
    def test_timeout(self, opener):
        """Сетевая ошибка завершается без автоматического повторного обращения."""
        opener.return_value.open.side_effect = URLError("secret endpoint")
        with self.assertRaisesRegex(ServiceError, "недоступен"):
            request_bytes("https://api")
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("src.transport.build_opener")
    def test_oversized_response(self, opener):
        """Размер внешнего ответа ограничивается до разбора JSON или HTML."""
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b"12345"
        with self.assertRaisesRegex(ServiceError, "размер"):
            request_bytes("https://api", limit=4)


class CodexTests(unittest.TestCase):
    """Проверяет параметры запуска, подписочную авторизацию и остановку процесса подменами."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "CODEX_API_KEY": "secret", "PATH": "/bin"}, clear=True)
    @patch("src.llm.codex_provider.subprocess.Popen")
    def test_subscription_environment_and_output(self, popen):
        """Ключи API исключаются из окружения дочернего Codex; JSON берётся из итогового файла."""
        def start(command, **kwargs):
            """Имитирует создание итогового файла без запуска исполняемого процесса."""
            Path(command[command.index("--output-last-message") + 1]).write_text("{}")
            return Mock(returncode=0)

        popen.side_effect = start
        result = generate_codex(ModelSettings("Codex CLI", "chosen"), "s", "p", CARD_SCHEMA)
        self.assertEqual(result, "{}")
        self.assertNotIn("OPENAI_API_KEY", popen.call_args.kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", popen.call_args.kwargs["env"])
        command = popen.call_args.args[0]
        self.assertIn("--ignore-user-config", command)
        self.assertIn("features.shell_tool=false", command)
        self.assertIn("read-only", command)
        self.assertEqual(command[command.index("--model") + 1], "chosen")

    @patch("src.llm.codex_provider.os.killpg")
    @patch("src.llm.codex_provider.subprocess.Popen")
    def test_timeout_stops_codex(self, popen, killpg):
        """Тайм-аут останавливает группу процессов вместо фонового продолжения генерации."""
        process = popen.return_value
        process.pid = 12345
        process.communicate.side_effect = [subprocess.TimeoutExpired("codex", 1), (None, None)]
        with self.assertRaisesRegex(ServiceError, "остановлен"):
            generate_codex(ModelSettings("Codex CLI", "chosen", timeout=1), "s", "p", CARD_SCHEMA)
        if os.name == "posix":
            killpg.assert_called_once()
        else:
            process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
