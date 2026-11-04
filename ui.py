"""Локальный интерфейс контент-менеджера: настройки, источники и копируемая карточка."""

import os
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from src.card.export import STATUS, json_report, markdown
from src.models import ServiceError
from src.llm.model_catalog import codex_models, load_models
from src.llm.providers import ModelSettings, PROVIDERS
from src.workflow import run


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
    """Показывает только список выбора и обновляет каталог по явному нажатию кнопки."""
    cache_key = ("model_catalog", provider, base_url.strip())
    if provider == "Codex CLI" and cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = codex_models()
        except ServiceError as exc:
            st.caption(str(exc))
    if st.button("Обновить список моделей", key=f"refresh_{provider}"):
        try:
            with st.spinner("Получаем список моделей…"):
                st.session_state[cache_key] = load_models(provider, base_url.strip())
        except ServiceError as exc:
            st.warning(str(exc))
    choices = st.session_state.get(cache_key, suggestions)
    model = st.selectbox(
        "Название модели", choices, key=f"model_{provider}_{base_url.strip()}",
        disabled=not choices, placeholder="Сначала загрузите список моделей",
    )
    if not choices:
        st.caption("Запустите сервер или настройте доступ, затем обновите список моделей.")
    elif cache_key not in st.session_state:
        st.caption("Показаны примеры моделей. Обновите список, чтобы получить каталог вашего сервиса.")
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
    raw = st.text_area("Данные одного товара (JSON)", height=340, key="product_json")
    enrich = st.checkbox("Дополнить данные со страницы товара", value=True)
    st.caption(
        "При включении загружается URL из JSON на souz-pribor.ru. Источники и добавленные сведения "
        "появятся в результате. При недоступности сайта используются исходные данные."
    )
    return raw, enrich


def render_sources(state):
    """Выводит конфликты отдельно и показывает происхождение допущенных характеристик."""
    facts = state.get("facts", {})
    for warning in state.get("warnings", []):
        st.warning(warning)
    if facts.get("conflicts"):
        st.error("Обнаружены конфликты. Спорные характеристики исключены из генерации.")
        rows = [{"Характеристика": c["field"], "Значение": v["value"], "Источник": v["source"]}
                for c in facts["conflicts"] for v in c["values"]]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    if facts.get("missing"):
        st.subheader("Нужно уточнить")
        for value in facts["missing"]:
            st.write("• " + value)
    with st.expander("Источники и дообогащение", expanded=False):
        page = facts.get("source_page")
        if page:
            st.write("Страница: " + page["url"])
            st.write("Заголовок: " + page["title"])
        if facts.get("added"):
            st.dataframe([
                {"Поле": item["field"], "Добавленные сведения": item["value"], "Источник": item["source"]}
                for item in facts["added"]
            ], hide_index=True, use_container_width=True)
        else:
            st.write("Сведения со страницы не добавлены.")
        for name, sources in facts.get("provenance", {}).items():
            st.write(name)
            for source in sources:
                st.caption(source["source"] + " — " + source["excerpt"])


def render_result(state):
    """Показывает статус и сохраняет предупреждения во всех экспортируемых форматах."""
    st.divider()
    st.subheader("Результат")
    st.info(STATUS.get(state.get("status"), "Обработка не завершена"))
    if state.get("error"):
        st.error(state["error"])
    render_sources(state)
    card = state.get("card")
    if card:
        st.subheader(card["seo_title"])
        left, right = st.columns(2)
        left.metric("Символов в заголовке", len(card["seo_title"]), help="Не более 70")
        right.metric("Символов в описании", len(card["seo_description"]), help="800–1200 с пробелами")
        st.write(card["seo_description"])
        st.subheader("Характеристики")
        st.table([{"Характеристика": k, "Значение": v} for k, v in state["facts"]["specs"].items()])
        st.subheader("Для менеджера")
        st.write(card["commercial"])
        st.subheader("Рекомендуемые поисковые запросы")
        for query in card["search_queries"]:
            st.write("• " + query)
        st.caption("Популярность запросов не проверялась. Перед публикацией проверьте все факты.")
    for issue in state.get("issues", []):
        st.error(issue)
    if state.get("provider"):
        st.caption(f"{state['provider']} · {state['model']} · обращений к модели: {state.get('attempts', 0)}")
    text, data = markdown(state), json_report(state)
    md_tab, json_tab = st.tabs(["Markdown для копирования", "JSON для копирования"])
    with md_tab:
        st.code(text, language="markdown")
        st.download_button("Скачать Markdown", text, "product-card.md", "text/markdown")
    with json_tab:
        st.code(data, language="json")
        st.download_button("Скачать JSON", data, "product-card.json", "application/json")
    with st.expander("Пройденные шаги графа"):
        st.write(" → ".join(state.get("steps", [])))


def main():
    """Генерирует карточку только по кнопке; изменения виджетов не вызывают модель."""
    st.set_page_config(page_title="Черновик карточки товара", page_icon="📝", layout="wide")
    st.title("Черновик карточки товара")
    st.write("Передайте сведения о приборе, выберите модель и получите текст для проверки контент-менеджером.")
    settings = connection_settings()
    raw, enrich = input_editor()
    signature = (raw, enrich, settings)
    if st.button("Сформировать черновик", type="primary"):
        st.session_state.pop("result", None)
        try:
            with st.spinner("Получаем факты и готовим карточку…"):
                st.session_state.result = run(raw, settings, enrich)
            st.session_state.result_signature = signature
        except ServiceError as exc:
            st.error(str(exc))
        except ImportError:
            st.error("Не установлены зависимости. Выполните python3 -m pip install -r requirements.txt.")
        except Exception:
            st.error("Внутренняя ошибка приложения. Результат не считается проверенным.")
    if "result" in st.session_state:
        if signature != st.session_state.get("result_signature"):
            st.warning("Настройки или вход изменены. Ниже показан предыдущий результат; нажмите кнопку для обновления.")
        render_result(st.session_state.result)


if __name__ == "__main__":
    main()
