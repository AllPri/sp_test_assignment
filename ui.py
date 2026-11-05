"""Локальный интерфейс контент-менеджера: настройки, источники и копируемая карточка."""

import os
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from src.models import ServiceError
from src.llm.model_catalog import load_models
from src.llm.providers import ModelSettings, PROVIDERS
from src.workflow import create_review_session, run
from src.demo.scenarios import label_result, load_scenarios
from src.ui.results import render_result
from src.ui.scenarios import clear_scenario, render_scenarios


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def connection_settings():
    """Позволяет выбрать провайдера и модель без сохранения настроек и ключей в файлы."""
    with st.sidebar:
        st.header("Подключение модели")
        provider = st.selectbox("Способ подключения", list(PROVIDERS))
        key_name, default_url, suggestions = PROVIDERS[provider]
        base_url = ""
        if provider == "Локальный API":
            base_url = st.text_input("Адрес API", default_url)
            st.caption("Совместимый /v1/chat/completions, например Ollama или llama.cpp. Сервер запускается отдельно.")
        elif provider == "Codex CLI":
            st.info("Используется установленный Codex с авторизацией через codex login.")
            st.caption("Клиент локальный, модель облачная. Действуют лимиты подписки.")
        model = model_selector(provider, base_url, suggestions)
        if key_name:
            if os.getenv(key_name):
                st.success(f"{key_name} настроен")
            elif provider == "Локальный API":
                st.caption("Ключ локального API не задан; для сервера без авторизации это допустимо.")
            else:
                st.warning(f"Добавьте {key_name} в .env и перезапустите приложение.")
        timeout = st.number_input("Ожидание модели, секунд", min_value=15, max_value=180, value=90, step=15)
        st.caption("На товар — максимум два обращения к выбранной модели. Автоматического переключения нет.")
    return ModelSettings(provider, model.strip(), base_url.strip(), int(timeout))


def model_selector(provider, base_url, suggestions):
    """Автоматически загружает каталог один раз при готовом подключении; ошибку повторяет только по кнопке."""
    cache_key = ("model_catalog", provider, base_url.strip())
    attempted_key = (*cache_key, "attempted")
    error_key = (*cache_key, "error")
    key_name = PROVIDERS[provider][0]
    ready = provider == "Codex CLI" or (provider == "Локальный API" and bool(base_url.strip()))
    ready = ready or bool(key_name and os.getenv(key_name))
    refresh = st.button("Обновить список моделей", key=f"refresh_{provider}")
    if refresh or (ready and attempted_key not in st.session_state):
        st.session_state[attempted_key] = True
        try:
            with st.spinner("Получаем список моделей…"):
                st.session_state[cache_key] = load_models(provider, base_url.strip())
            st.session_state.pop(error_key, None)
        except ServiceError as exc:
            st.session_state[error_key] = str(exc)
    if error_key in st.session_state:
        st.warning(st.session_state[error_key])
    choices = st.session_state.get(cache_key, suggestions)
    model = st.selectbox(
        "Название модели", choices, key=f"model_{provider}_{base_url.strip()}",
        disabled=not choices, placeholder="Сначала загрузите список моделей",
    )
    if not choices:
        st.caption("Запустите сервер или настройте доступ, затем обновите список моделей.")
    elif cache_key not in st.session_state:
        st.caption("Показаны примеры моделей, а не каталог аккаунта. Настройте доступ или повторите обновление списка.")
    elif provider == "Codex CLI":
        st.caption("Список из локального кэша Codex. Он может устареть; кэш обновляет сам Codex.")
    else:
        st.caption("Список получен от выбранного сервиса. Поддержка нужного формата проверяется при генерации.")
    return model or ""


def input_editor():
    """Загружает выбранный пример и оставляет JSON редактируемым перед генерацией."""
    examples = {"Модуль МК110": "mk110.json", "Модем ПМ01-24.АВ": "pm01.json"}
    selected = st.selectbox("Исходный пример", list(examples))
    if "product_json" not in st.session_state:
        st.session_state.product_json = (ROOT / "examples" / examples[selected]).read_text(encoding="utf-8")
    if st.button("Подставить выбранный пример"):
        st.session_state.product_json = (ROOT / "examples" / examples[selected]).read_text(encoding="utf-8")
        clear_scenario()
        st.session_state.enrich_enabled = True
    with st.expander("Исходные данные товара (JSON)", expanded="result" not in st.session_state):
        raw = st.text_area("Данные одного товара (JSON)", height=260, key="product_json")
    if "enrich_enabled" not in st.session_state:
        st.session_state.enrich_enabled = True
    enrich = st.checkbox("Дополнить данные со страницы товара", key="enrich_enabled")
    st.caption(
        "Если значения JSON и сайта различаются, предложим выбрать правильное перед генерацией."
    )
    return raw, enrich


def render_editor(settings):
    """Применяет демонстрационный источник только при явном выборе сценария."""
    scenario_id = st.session_state.get("demo_scenario_id")
    scenario = load_scenarios().get(scenario_id)
    if scenario:
        st.warning("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ: " + scenario.title + ". Вместо сайта используется локальный источник.")
        st.button("Отключить демонстрационный режим", on_click=clear_scenario)
    raw, enrich = input_editor()
    # Выбор обычного примера может отключить демонстрацию в текущем обновлении.
    scenario = load_scenarios().get(st.session_state.get("demo_scenario_id"))
    signature = (raw, enrich, settings, scenario.id if scenario else None)
    if st.button("Сформировать черновик", type="primary"):
        st.session_state.pop("result", None)
        st.session_state.pop("review_session", None)
        try:
            with st.spinner("Получаем факты и готовим карточку…"):
                if scenario:
                    session = create_review_session(settings, fetcher=scenario.fetch)
                    result = run(raw, settings, enrich, fetcher=scenario.fetch, session=session)
                    st.session_state.result = label_result(result, scenario)
                else:
                    session = create_review_session(settings)
                    st.session_state.result = run(raw, settings, enrich, session=session)
                st.session_state.review_session = session
            st.session_state.result_signature = signature
        except ServiceError as exc:
            st.error(str(exc))
        except ImportError:
            st.error("Не установлены зависимости. Выполните python3 -m pip install -r requirements.txt.")
        except Exception:
            st.error("Внутренняя ошибка приложения. Результат не считается проверенным.")
    if "result" in st.session_state:
        stale = signature != st.session_state.get("result_signature")
        if stale:
            st.warning("Настройки или вход изменены. Ниже показан предыдущий результат; нажмите кнопку для обновления.")
        render_result(st.session_state.result, review_session=st.session_state.get("review_session"), stale=stale)


def main():
    """Разделяет рабочий редактор и воспроизводимые сценарии; сам выбор вкладки модель не вызывает."""
    st.set_page_config(page_title="Черновик карточки товара", page_icon="📝", layout="wide")
    st.title("Черновик карточки товара")
    st.write("Передайте сведения о приборе, выберите модель и получите текст для проверки контент-менеджером.")
    settings = connection_settings()
    editor, scenarios = st.tabs(["Карточка товара", "Примеры сценариев"])
    with editor:
        render_editor(settings)
    with scenarios:
        render_scenarios()


if __name__ == "__main__":
    main()
