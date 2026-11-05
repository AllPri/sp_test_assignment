"""Проверяет настоящий interrupt/resume, изоляцию карточек и сохранение замечаний специалиста."""

from copy import deepcopy
import importlib.util
import json
import unittest
from unittest.mock import Mock, patch

from src.card.export import json_report, markdown
from src.card.review import validate_decision
from src.llm.providers import ModelSettings
from src.models import InputError
from src.sources.website import PageFacts
from src.workflow import create_review_session, resume_review, run


SETTINGS = ModelSettings("Локальный API", "test", "http://localhost:1/v1")
RAW = json.dumps({"name": "Прибор", "specs": {"Питание": "24 В", "Интерфейс": "RS-485"}})
CARD = {"seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
        "search_queries": ["прибор", "выбор прибора", "заказать прибор"], "commercial": "Для задач предприятия."}


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "LangGraph не установлен")
class HumanReviewTests(unittest.TestCase):
    """Доказывает, что решение возобновляет только ручной узел без повторной генерации."""

    def setUp(self):
        """Создаёт отдельный граф с моделью-подменой и ожидающей карточкой."""
        self.generator = Mock(return_value=json.dumps(CARD, ensure_ascii=False))
        self.session = create_review_session(SETTINGS, generator=self.generator)
        self.state = run(RAW, SETTINGS, False, session=self.session)

    def test_interrupt_and_approve_no_second_model_call(self):
        """До решения карточка не подтверждена; после продолжения в экспорте есть специалист и время."""
        self.assertEqual(self.state["review"]["status"], "pending")
        self.assertTrue(self.state.get("__interrupt__"))
        state = resume_review(self.session, self.state, {"decision": "approve", "reviewer": "Иванов", "comment": "Проверено"})
        self.assertEqual(state["status"], "approved")
        self.assertEqual(self.generator.call_count, 1)
        self.assertIn("Ручная проверка специалистом", state["steps"])
        self.assertTrue(state["review"]["card_sha256"])
        for output in (json_report(state), markdown(state)):
            self.assertIn("Иванов", output)
            self.assertIn(state["review"]["reviewed_at"], output)

    def test_reject_and_duplicate_decision(self):
        """Отклонение сохраняется; уже завершённую проверку нельзя подтвердить повторным запросом."""
        state = resume_review(self.session, self.state, {"decision": "reject", "reviewer": "Петров", "comment": "Уточнить паспорт"})
        self.assertEqual(state["status"], "rejected")
        with self.assertRaises(InputError):
            resume_review(self.session, state, {"decision": "approve", "reviewer": "Петров"})

    def test_invalid_form_does_not_poison_checkpoint(self):
        """После ошибки формы можно отправить исправленное решение в тот же узел."""
        with self.assertRaises(InputError):
            resume_review(self.session, self.state, {"decision": "approve", "reviewer": ""})
        result = resume_review(self.session, self.state, {"decision": "approve", "reviewer": "Специалист"})
        self.assertEqual(result["status"], "approved")

    def test_changed_card_cannot_reuse_review(self):
        """Решение нельзя применить к изменённому тексту или чужой карточке."""
        altered = deepcopy(self.state)
        altered["card"]["seo_title"] = "Другой прибор"
        with self.assertRaises(InputError):
            resume_review(self.session, altered, {"decision": "approve", "reviewer": "Специалист"})

    def test_issues_require_comment_and_acknowledgement(self):
        """Ручное подтверждение не стирает автоматические ошибки и требует осознанного решения."""
        generator = Mock(return_value=json.dumps({**CARD, "seo_description": "Короткое описание"}))
        session = create_review_session(SETTINGS, generator=generator)
        state = run(RAW, SETTINGS, False, session=session)
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(generator.call_count, 2)
        with self.assertRaises(InputError):
            resume_review(session, state, {"decision": "approve", "reviewer": "Специалист"})
        reviewed = resume_review(session, state, {"decision": "approve", "reviewer": "Специалист",
                               "comment": "Согласовано сокращение текста", "acknowledge_issues": True})
        self.assertEqual(reviewed["issues"], state["issues"])
        self.assertEqual(reviewed["review"]["automatic_status"], "needs_review")

    @patch.dict("os.environ", {"LANGGRAPH_STRICT_MSGPACK": "true"})
    def test_checkpoint_supports_page_without_custom_objects(self):
        """Источники остаются простыми данными и восстанавливаются без небезопасной десериализации."""
        fetcher = Mock(return_value=PageFacts("demo://page", specs={"Питание": "24 В"}))
        session = create_review_session(SETTINGS, generator=self.generator, fetcher=fetcher)
        raw = json.dumps({**json.loads(RAW), "url": "demo://page"})
        state = run(raw, SETTINGS, session=session)
        state["demonstration"] = {"scenario": "test"}
        state["warnings"].append("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ")
        reviewed = resume_review(session, state, {"decision": "approve", "reviewer": "Специалист"})
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(reviewed["demonstration"], state["demonstration"])
        self.assertIn("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ", reviewed["warnings"])
        fetcher.assert_called_once()

    def test_unformed_card_cannot_be_reviewed(self):
        """Ошибка формата или недостаток данных не превращаются в подтверждённую карточку."""
        with self.assertRaises(InputError):
            validate_decision({"card": None}, {"decision": "approve", "reviewer": "Специалист"})


if __name__ == "__main__":
    unittest.main()
