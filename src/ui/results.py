"""Отображает карточку, источники, конфликты и копируемые результаты."""

import streamlit as st

from ..card.export import STATUS, json_report, markdown
from .review import render_review


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


def render_result(state, *, key_prefix="result", review_session=None, stale=False):
    """Показывает статус и сохраняет предупреждения во всех экспортируемых форматах."""
    st.divider()
    st.subheader("Результат")
    st.info(STATUS.get(state.get("status"), "Обработка не завершена"))
    if state.get("error"):
        st.error(state["error"])
    for issue in state.get("issues", []):
        st.error(issue)
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
    elif state.get("facts", {}).get("specs"):
        st.subheader("Подтверждённые характеристики")
        st.table([{"Характеристика": k, "Значение": v} for k, v in state["facts"]["specs"].items()])
    if state.get("provider"):
        st.caption(f"{state['provider']} · {state['model']} · обращений к модели: {state.get('attempts', 0)}")
    render_review(state, review_session, stale=stale)
    text, data = markdown(state), json_report(state)
    md_tab, json_tab = st.tabs(["Markdown для копирования", "JSON для копирования"])
    with md_tab:
        st.code(text, language="markdown")
        st.download_button("Скачать Markdown", text, "product-card.md", "text/markdown", key=key_prefix + "_md")
    with json_tab:
        st.code(data, language="json")
        st.download_button("Скачать JSON", data, "product-card.json", "application/json", key=key_prefix + "_json")
    with st.expander("Пройденные шаги графа"):
        st.write(" → ".join(state.get("steps", [])))


