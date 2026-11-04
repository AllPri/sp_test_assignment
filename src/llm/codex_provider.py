"""Вызывает локальный Codex CLI с сохранённой авторизацией и ограниченными возможностями."""

import json
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryDirectory

from ..models import ServiceError


def generate_codex(settings, system, prompt, schema):
    """Получает только итоговый JSON; каждый товар запускается в отдельной временной папке."""
    with TemporaryDirectory(prefix="product-card-") as directory:
        folder = Path(directory)
        schema_path = folder / "schema.json"
        output_path = folder / "answer.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        command = [
            "codex", "exec", "--ignore-user-config", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only",
            "-c", 'web_search="disabled"', "-c", "features.shell_tool=false",
            "-c", "features.unified_exec=false", "-c", "mcp_servers={}",
            "--model", settings.model, "--output-schema", str(schema_path),
            "--output-last-message", str(output_path), "-",
        ]
        # Исключаем случайный расход API-ключа вместо авторизации через подписку.
        environment = {k: v for k, v in os.environ.items()
                       if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, text=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name == "posix",
                cwd=folder, env=environment,
            )
        except OSError:
            raise ServiceError("Не удалось запустить codex. Проверьте установку и PATH.") from None
        try:
            process.communicate(system + "\n\n" + prompt, timeout=settings.timeout)
        except subprocess.TimeoutExpired:
            # Останавливаем также дочерний процесс исполняемого файла Codex на Linux/macOS.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.communicate()
            raise ServiceError("Codex не ответил вовремя. Процесс остановлен.") from None
        if process.returncode or not output_path.exists():
            raise ServiceError(
                "Codex завершился без результата. Проверьте codex login, лимиты, "
                "доступность модели и поддержку параметров вашей версией CLI."
            )
        if output_path.stat().st_size > 100_000:
            raise ServiceError("Codex вернул слишком большой результат.")
        return output_path.read_text(encoding="utf-8")
