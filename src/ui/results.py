"""Показывает карточку или короткую форму расхождений, оставляя диагностику свёрнутой."""

import streamlit as st

from ..card.export import STATUS, json_report, markdown
from .review import render_review


def render_sources(state):
    """Хранит причины пропуска данных и происхождение параметров в одном свёрнутом блоке."""
    facts = state.get("facts", {})
    with st.expander("Источники и дообогащение", expanded=False):
        for warning in state.get("warnings", []):
            st.write(warning)
        page = facts.get("source_page")
        if page:
            st.write("Страница: " + page["url"])
            st.caption(page.get("title", ""))
        if facts.get("missing"):
            st.write("Не указано: " + "; ".join(facts["missing"]))
        if facts.get("conflicts"):
            st.write("Исключённые противоречивые сведения:")
            st.dataframe([{"Параметр": c["field"], "Значение": v["value"], "Источник": v["source"]}
                          for c in facts["conflicts"] for v in c["values"]], hide_index=True)
        for name, sources in facts.get("provenance", {}).items():
            st.write(name)
            for source in sources:
                st.caption(source["source"] + " — " + source["excerpt"])
        resolutions = state.get("review", {}).get("resolutions", [])
        if resolutions:
            st.write("Выбранные значения:")
            st.dataframe([{"Параметр": r["field"], "Значение": r["value"], "Источник": r["source"]}
                          for r in resolutions], hide_index=True)


def render_exports(state, key_prefix):
    """Не загромождает карточку исходниками JSON и Markdown, сохраняя копирование и скачивание."""
    with st.expander("Скопировать или скачать результат", expanded=False):
        md_tab, json_tab = st.tabs(["Markdown", "JSON"])
        with md_tab:
            text = markdown(state)
            st.code(text, language="markdown")
            st.download_button("Скачать Markdown", text, "product-card.md", "text/markdown", key=key_prefix + "_md")
        with json_tab:
            data = json_report(state)
            st.code(data, language="json")
            st.download_button("Скачать JSON", data, "product-card.json", "application/json", key=key_prefix + "_json")


def render_result(state, *, key_prefix="result", review_session=None, stale=False, on_resolved=None):
    """Не просит подтверждать готовую карточку; человек отвечает только на различающиеся значения."""
    st.divider()
    pending = state.get("status") == "awaiting_resolution"
    if pending:
        render_review(state, review_session, stale=stale, on_resolved=on_resolved)
    else:
        st.subheader("Результат")
        if state.get("status") == "draft":
            st.success("Черновик готов")
        else:
            st.info(STATUS.get(state.get("status"), "Обработка не завершена"))
    if state.get("error"):
        st.error(state["error"])
    if state.get("issues"):
        st.warning("После автоматической доработки остались замечания. Можно повторить генерацию или дополнить исходные данные.")
        with st.expander("Замечания автоматической проверки", expanded=False):
            for issue in state["issues"]:
                st.write(issue)
    card = state.get("card")
    if card:
        st.subheader(card["seo_title"])
        st.caption(f"Заголовок: {len(card['seo_title'])}/70 символов · Описание: {len(card['seo_description'])}/800–1200 символов")
        st.write(card["seo_description"])
        st.subheader("Характеристики")
        st.table([{"Параметр": k, "Значение": v} for k, v in state["facts"]["specs"].items()])
        st.subheader("Для менеджера")
        st.write(card["commercial"])
        st.subheader("Поисковые запросы")
        for query in card["search_queries"]:
            st.write("• " + query)
        st.caption("Черновик для редакторской проверки перед публикацией.")
    elif not pending and state.get("facts", {}).get("specs"):
        st.table([{"Параметр": k, "Значение": v} for k, v in state["facts"]["specs"].items()])
    if state.get("review", {}).get("status") == "resolved":
        st.caption("Выбранные значения применены. История выбора сохранена в результатах.")
    render_sources(state)
    if not pending:
        render_exports(state, key_prefix)
    with st.expander("Технические подробности", expanded=False):
        if state.get("provider"):
            st.caption(f"{state['provider']} · {state['model']} · обращений к модели: {state.get('attempts', 0)}")
        st.write(" → ".join(state.get("steps", [])))
