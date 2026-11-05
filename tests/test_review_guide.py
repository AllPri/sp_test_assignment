"""Проверяет, что на оператора выносятся только различия между локальными данными и сайтом."""

import unittest

from src.card.review_guide import build_review_guide


class ReviewGuideTests(unittest.TestCase):
    """Не допускает общих анкет, вопросов об SEO, длине или пропущенных параметрах."""

    def test_local_site_conflict_has_explicit_choices(self):
        """Варианты содержат исходные значения и источники, а не поле свободного комментария."""
        facts = {"source_page": {"url": "https://example.test"}, "conflicts": [
            {"field": "Питание", "values": [{"value": "24 В", "source": "Входной JSON"},
                                             {"value": "220 В", "source": "https://example.test"}]}]}
        tasks = build_review_guide({"facts": facts})
        self.assertEqual(len(tasks), 1)
        self.assertEqual([v["value"] for v in tasks[0]["choices"]], ["24 В", "220 В"])
        self.assertTrue(tasks[0]["id"])

    def test_missing_values_warnings_and_text_errors_are_not_questions(self):
        """Даже несколько диагностических сообщений не создают поручений оператору."""
        state = {"issues": ["Описание: 500 символов, нужно от 800 до 1200."],
                 "facts": {"missing": ["Питание", "Производитель"], "conflicts": [],
                           "source_page": {"url": "source", "warnings": ["На странице сравниваются версии."]}}}
        self.assertEqual(build_review_guide(state), [])

    def test_single_source_conflict_not_sent_to_operator(self):
        """Проблемы внутри одной стороны не выдаются за расхождение локального товара с сайтом."""
        for sources in (("Входной JSON", "Входной JSON: description"), ("source", "source")):
            facts = {"source_page": {"url": "source"}, "conflicts": [{"field": "Питание", "values": [
                {"value": "24 В", "source": sources[0]}, {"value": "220 В", "source": sources[1]}]}]}
            self.assertEqual(build_review_guide({"facts": facts}), [])

    def test_duplicate_local_value_does_not_repeat_option(self):
        """Одинаковые данные specs и description не превращаются в два одинаковых ответа."""
        facts = {"source_page": {"url": "site"}, "conflicts": [{"field": "Питание", "values": [
            {"value": "24 В", "source": "Входной JSON"},
            {"value": "24 В", "source": "Входной JSON: description"},
            {"value": "220 В", "source": "site"}]}]}
        self.assertEqual(len(build_review_guide({"facts": facts})[0]["choices"]), 2)


if __name__ == "__main__":
    unittest.main()
