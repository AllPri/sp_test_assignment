"""Показывает сценарии и позволяет проверить данные до обращения к модели."""

import streamlit as st

from ..demo.scenarios import load_scenarios, preview_scenario
from .results import render_result


def apply_scenario(scenario_id):
    """Подставляет пример перед построением виджетов при следующем обновлении страницы."""
    scenario = load_scenarios()[scenario_id]
    st.session_state.product_json = scenario.raw
    st.session_state.enrich_enabled = scenario.enrich
    st.session_state.demo_scenario_id = scenario_id
    st.session_state.pop("result", None)


def clear_scenario():
    """Отключает локальную подмену источника для обычной работы с товаром."""
    st.session_state.pop("demo_scenario_id", None)


def render_scenarios():
    """Отделяет ожидаемую реакцию от фактического результата общего графа."""
    st.subheader("Примеры сценариев")
    st.info("Демонстрационные данные: вымышленные приборы и локальные HTML-страницы. Сайт заказчика не запрашивается.")
    scenarios = load_scenarios()
    selected = st.selectbox("Сценарий", list(scenarios), format_func=lambda key: scenarios[key].title)
    scenario = scenarios[selected]
    st.write(scenario.explanation)
    st.write("Ожидаемая реакция: " + scenario.expected)
    with st.expander("Исходные данные и демонстрационный источник", expanded=False):
        st.code(scenario.raw, language="json")
        if scenario.source_url:
            st.write("Локальный источник: " + scenario.source_url)
        if scenario.source_html:
            from ..demo.scenarios import FOLDER
            st.code((FOLDER / scenario.source_html).read_text(encoding="utf-8"), language="html")
    if st.button("Проверить сценарий без модели"):
        with st.spinner("Проверяем данные…"):
            st.session_state.scenario_preview = (selected, preview_scenario(scenario))
    st.button("Подставить в редактор", on_click=apply_scenario, args=(selected,))
    st.caption("После подстановки откройте вкладку «Карточка товара». Генерация запускается её обычной кнопкой и использует выбранную модель.")
    saved = st.session_state.get("scenario_preview")
    if saved and saved[0] == selected:
        render_result(saved[1], key_prefix="scenario")
