"""Показывает форму решения специалиста для приостановленного узла LangGraph."""

import streamlit as st

from ..models import InputError
from ..workflow import resume_review


def render_review(state, session=None, *, stale=False):
    """Подтверждает конкретный результат без повторного вызова модели и без удаления замечаний."""
    review = state.get("review", {})
    if not state.get("card"):
        return
    st.subheader("Ручная проверка специалистом")
    if review.get("status") in ("approved", "rejected"):
        decision = "Подтверждено" if review["status"] == "approved" else "Отклонено"
        st.write(f"{decision}: {review['reviewer']} · {review['reviewed_at']}")
        if review.get("comment"):
            st.write("Комментарий: " + review["comment"])
        return
    st.info("Черновик ожидает ручной проверки. Изучите текст, характеристики, источники и автоматические замечания.")
    if session is None:
        st.caption("Этот результат не связан с активной проверкой в редакторе. Подтверждение специалиста не выполнено.")
        return
    if stale:
        st.warning("Входные данные или настройки изменены. Сформируйте новый черновик перед подтверждением.")
        return
    concerns = bool(state.get("issues") or state.get("facts", {}).get("conflicts"))
    with st.form("specialist_review_" + session["config"]["configurable"]["thread_id"]):
        reviewer = st.text_input("Специалист (имя)", max_chars=120)
        decision = st.radio("Решение специалиста", ("Подтвердить", "Отклонить"))
        comment = st.text_area("Комментарий специалиста", max_chars=2000)
        acknowledge = st.checkbox("Я изучил автоматические замечания и конфликты") if concerns else False
        submitted = st.form_submit_button("Сохранить решение специалиста")
    if submitted:
        try:
            st.session_state.result = resume_review(session, state, {
                "reviewer": reviewer, "decision": "approve" if decision == "Подтвердить" else "reject",
                "comment": comment, "acknowledge_issues": acknowledge,
            })
            st.rerun()
        except InputError as exc:
            st.error(str(exc))
