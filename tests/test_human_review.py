"""Проверяет выбор значений до генерации и отсутствие лишних обращений к оператору."""

from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from src.card.export import json_report
from src.card.review_guide import build_review_guide
from src.llm.providers import ModelSettings
from src.models import InputError
from src.sources.website import PageFacts
from src.workflow import create_review_session, resume_review, run


SETTINGS = ModelSettings("Локальный API", "test", "http://localhost:1/v1")
URL = "https://www.souz-pribor.ru/product/test/"
RAW = json.dumps({"name": "Прибор", "manufacturer": "Завод", "url": URL,
                  "specs": {"Питание": "24 В", "Интерфейс": "RS-485", "Степень защиты": "IP20"}})
CARD = {"seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
        "search_queries": ["прибор", "выбор прибора", "заказать прибор"], "commercial": "Для задач предприятия."}


class HumanReviewTests(unittest.TestCase):
    """Оператор выбирает только при реальном конфликте локального значения со страницей."""

    def setUp(self):
        """Создаёт граф с противоположными значениями питания и подставной моделью."""
        self.generator = Mock(return_value=json.dumps(CARD))
        self.fetcher = Mock(return_value=PageFacts(URL, specs={"Питание": "220 В"}))
        self.session = create_review_session(SETTINGS, generator=self.generator, fetcher=self.fetcher)
        self.state = run(RAW, SETTINGS, session=self.session)
        self.task = build_review_guide(self.state)[0]

    def choose(self, index):
        """Продолжает граф с одним явно выбранным ответом."""
        return resume_review(self.session, self.state, {"choices": {self.task["id"]: index}})

    def test_stops_before_model_and_uses_site_choice(self):
        """До выбора запросов к модели нет; после выбора 220 В попадают в реальный промпт."""
        self.assertEqual(self.state["status"], "awaiting_resolution")
        self.assertIsNone(self.state["card"])
        self.generator.assert_not_called()
        state = self.choose(1)
        self.assertEqual(state["status"], "draft")
        self.assertEqual(state["facts"]["specs"]["Питание"], "220 В")
        self.assertIn("220 В", self.generator.call_args.args[2])
        self.assertNotIn("24 В", self.generator.call_args.args[2])
        self.assertEqual(state["review"]["status"], "resolved")
        self.assertEqual(self.generator.call_count, 1)
        self.fetcher.assert_called_once()
        self.assertIn('"resolutions"', json_report(state))

    def test_local_choice_and_unknown(self):
        """Можно оставить локальный вариант или явно исключить неподтверждённый параметр."""
        state = self.choose(0)
        self.assertEqual(state["facts"]["specs"]["Питание"], "24 В")
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=self.fetcher)
        pending = run(RAW, SETTINGS, session=session)
        task = build_review_guide(pending)[0]
        state = resume_review(session, pending, {"choices": {task["id"]: -1}})
        self.assertEqual(state["facts"]["specs"]["Питание"], "данных нет")
        self.assertNotIn("220 В", self.generator.call_args.args[2])
        self.assertNotIn("24 В", self.generator.call_args.args[2])

    def test_incomplete_or_forged_choice_does_not_resume(self):
        """Ни один источник не выбирается по умолчанию; произвольное значение передать нельзя."""
        for answers in ({}, {self.task["id"]: None}, {self.task["id"]: 10}, {self.task["id"]: True}):
            with self.subTest(answers=answers), self.assertRaises(InputError):
                resume_review(self.session, self.state, {"choices": answers})
        self.generator.assert_not_called()
        self.assertEqual(self.choose(0)["status"], "draft")

    def test_changed_inputs_and_repeated_choice_rejected(self):
        """Решение привязано к одному набору исходных данных и применяется один раз."""
        altered = deepcopy(self.state)
        altered["facts"]["specs"]["Интерфейс"] = "RS-232"
        with self.assertRaises(InputError):
            resume_review(self.session, altered, {"choices": {self.task["id"]: 0}})
        state = self.choose(0)
        with self.assertRaises(InputError):
            resume_review(self.session, state, {"choices": {self.task["id"]: 0}})

    def test_no_conflict_means_no_human_step(self):
        """Согласованные данные и предупреждения о версии не требуют подтверждения человеком."""
        fetcher = Mock(return_value=PageFacts(URL, specs={"Питание": "24 В"}, warnings=["На странице сравниваются версии."]))
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=fetcher)
        state = run(RAW, SETTINGS, session=session)
        self.assertEqual(state["status"], "draft")
        self.assertEqual(state["review"]["status"], "not_required")
        self.assertFalse(state.get("__interrupt__"))
        self.assertFalse(build_review_guide(state))

    def test_automatic_format_failure_does_not_ask_operator(self):
        """Короткий ответ дорабатывается автоматически, затем остаётся ошибкой сервиса, а не анкетой."""
        generator = Mock(return_value=json.dumps({**CARD, "seo_description": "Коротко"}))
        session = create_review_session(SETTINGS, generator=generator)
        state = run(RAW, SETTINGS, False, session=session)
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(generator.call_count, 2)
        self.assertFalse(state.get("__interrupt__"))
        self.assertFalse(build_review_guide(state))

    def test_unknown_value_can_leave_insufficient_data(self):
        """После отказа от единственного параметра не начинается генерация по пустым данным."""
        raw = json.dumps({"name": "Прибор", "url": URL, "specs": {"Питание": "24 В"}})
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=self.fetcher)
        state = run(raw, SETTINGS, session=session)
        task = build_review_guide(state)[0]
        state = resume_review(session, state, {"choices": {task["id"]: -1}})
        self.assertEqual(state["status"], "insufficient_data")
        self.generator.assert_not_called()

    def test_conflicts_only_inside_json_do_not_interrupt(self):
        """Противоречие внутри локального описания исключается без перевода всех вопросов на оператора."""
        raw = json.dumps({"name": "Прибор", "specs": {"Питание": "24 В", "Интерфейс": "RS-485", "Защита корпуса": "IP20"},
                          "description": "Питание прибора 220 В."})
        session = create_review_session(SETTINGS, generator=self.generator)
        state = run(raw, SETTINGS, False, session=session)
        self.assertEqual(state["status"], "draft")
        self.assertFalse(build_review_guide(state))
        self.assertNotIn("Питание", state["facts"]["specs"])

    def test_each_conflict_requires_its_own_answer(self):
        """Два спорных параметра требуют двух выборов; ни один не подтверждается за другой."""
        fetcher = Mock(return_value=PageFacts(URL, specs={"Питание": "220 В", "Интерфейс": "RS-232"}))
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=fetcher)
        pending = run(RAW, SETTINGS, session=session)
        tasks = build_review_guide(pending)
        self.assertEqual(len(tasks), 2)
        with self.assertRaises(InputError):
            resume_review(session, pending, {"choices": {tasks[0]["id"]: 0}})
        self.generator.assert_not_called()
        result = resume_review(session, pending, {"choices": {task["id"]: 1 for task in tasks}})
        self.assertEqual(result["facts"]["specs"]["Питание"], "220 В")
        self.assertEqual(result["facts"]["specs"]["Интерфейс"], "RS-232")

    def test_site_internal_conflict_retains_local_candidate(self):
        """Если сайт сам противоречив, локальное значение не теряется среди его вариантов."""
        page = PageFacts(URL, conflicts=[{"field": "Питание", "values": [
            {"value": "220 В", "source": URL}, {"value": "240 В", "source": URL}]}])
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=Mock(return_value=page))
        pending = run(RAW, SETTINGS, session=session)
        task = build_review_guide(pending)[0]
        self.assertEqual([v["value"] for v in task["choices"]], ["24 В", "220 В", "240 В"])
        result = resume_review(session, pending, {"choices": {task["id"]: 0}})
        self.assertEqual(result["facts"]["specs"]["Питание"], "24 В")

    def test_selected_source_keeps_unit_in_its_field_name(self):
        """Если единица записана в заголовке сайта, она не теряется после выбора его значения."""
        field = "Диапазон напряжений питания постоянного тока ПМ01-24.АВ, В"
        fetcher = Mock(return_value=PageFacts(URL, specs={field: "от 10 до 30"}))
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=fetcher)
        pending = run(RAW, SETTINGS, session=session)
        task = build_review_guide(pending)[0]
        result = resume_review(session, pending, {"choices": {task["id"]: 1}})
        self.assertEqual(result["facts"]["specs"][field], "от 10 до 30")
        self.assertNotIn("Питание", result["facts"]["specs"])


if __name__ == "__main__":
    unittest.main()
