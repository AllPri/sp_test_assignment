"""Запускает локальный интерфейс тем же интерпретатором, что запустил main.py."""

import importlib.util
from pathlib import Path
import subprocess
import sys


def main():
    """Открывает Streamlit только после явного запуска пользователем."""
    if importlib.util.find_spec("streamlit") is None:
        raise SystemExit("Установите зависимости: python3 -m pip install -r requirements.txt")
    app = Path(__file__).resolve().parent / "ui.py"
    result = subprocess.run([
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false",
    ], check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
