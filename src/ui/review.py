"""Показывает отдельный выбор для каждого расхождения локальных данных с сайтом."""

import streamlit as st

from ..card.review_guide import build_review_guide, is_local
from ..models import InputError
from ..workflow import resume_review


def option_label(task, index):
    """Подписывает варианты без технических идентификаторов и сложных форм согласования."""
    if index == -1:
        return "Пока неизвестно — оставить «данных нет»"
    choice = task["choices"][index]
    origin = "Локальные данные" if is_local(choice["source"]) else "Сайт"
    return origin + ": " + choice["value"]


def render_review(state, session=None, *, stale=False):
    """Запрашивает выбор до генерации; при согласованных данных вообще не показывает форму."""
    tasks = build_review_guide(state)
    if not tasks or state.get("status") != "awaiting_resolution":
        return
    st.subheader("Выберите правильные значения")
    st.write("Локальные данные отличаются от сайта. Выберите значение для каждого параметра — затем карточка сформируется автоматически.")
    if session is None:
        st.caption("Чтобы сделать выбор, подставьте этот сценарий в редактор и начните подготовку карточки.")
        return
    if stale:
        st.warning("Исходные данные изменены. Нажмите «Сформировать черновик» ещё раз.")
        return
    answers = {}
    with st.form("resolve_" + session["config"]["configurable"]["thread_id"]):
        for task in tasks:
            with st.container(border=True):
                st.markdown("**" + task["field"] + "**")
                local_column, site_column = st.columns(2)
                for column, local in ((local_column, True), (site_column, False)):
                    with column:
                        st.caption("Локальные данные" if local else "На сайте")
                        for choice in task["choices"]:
                            if is_local(choice["source"]) == local:
                                st.write(choice["value"])
                                if choice.get("field") and choice["field"] != task["field"]:
                                    st.caption(choice["field"])
                answers[task["id"]] = st.radio(
                    task["field"] + ": какое значение использовать?",
                    list(range(len(task["choices"]))) + [-1], index=None,
                    format_func=lambda index, item=task: option_label(item, index),
                    key="choice_" + session["config"]["configurable"]["thread_id"] + task["id"],
                )
                with st.expander("Посмотреть подтверждающие фрагменты", expanded=False):
                    for choice in task["choices"]:
                        st.caption(choice["source"])
                        st.write(choice.get("excerpt") or choice["value"])
        submitted = st.form_submit_button("Применить выбор и сформировать карточку", type="primary")
    if submitted:
        try:
            with st.spinner("Готовим карточку с выбранными значениями…"):
                st.session_state.result = resume_review(session, state, {"choices": answers})
            st.rerun()
        except InputError as exc:
            st.error(str(exc))
