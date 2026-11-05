"""Проверяет контекст частоты на примере сохранённой пользователем карточки МК110."""

import unittest

from src.card.claims import check_claims
from src.card.extraction import extract_text


class FrequencyTests(unittest.TestCase):
    """Различает входной сигнал, питание и частоту в условии измерения импульса."""

    def setUp(self):
        """Воспроизводит исходные строки таблицы, где единицы находятся в заголовках."""
        self.facts = {"specs": {
            "Максимальная частота сигнала, подаваемого на дискретный вход, кГц": "1",
            "Минимальная длительность импульса, воспринимаемого дискретным входом, мс":
                "0.5 (скважность 2 для частоты 1 кГц)",
            "Частота питания, Гц": "50",
        }, "descriptions": []}

    def claims(self, text):
        """Проверяет выбранную фразу без ограничений длины, не относящихся к этой ошибке."""
        card = {"seo_title": "Модуль", "seo_description": text, "commercial": "", "search_queries": []}
        return check_claims(card, self.facts)

    def test_user_phrase_and_parenthetical_condition_pass(self):
        """Слова о максимуме и условии импульса остаются связанными с нужными исходными строками."""
        text = ("Максимальная частота сигнала, подаваемого на дискретный вход, — 1 кГц. "
                "Минимальная длительность воспринимаемого импульса — 0.5 мс "
                "(скважность 2 для частоты 1 кГц).")
        self.assertEqual(self.claims(text), [])
        names = {fact["name"] for fact in extract_text(text, "Ответ модели", include_custom=False)}
        self.assertIn("Максимальная частота входного сигнала", names)
        self.assertIn("Частота в условии длительности импульса", names)
        self.assertNotIn("Частота", names)

    def test_wrong_maximum_still_rejected(self):
        """Новый максимум не разрешается наличием другого числа в таблице."""
        self.assertTrue(self.claims("Максимальная частота входного сигнала — 2 кГц."))

    def test_power_frequency_does_not_borrow_input_limit(self):
        """1 кГц входного сигнала не подтверждает питание с частотой 1 кГц."""
        self.assertTrue(self.claims("Частота питания — 1 кГц."))
        self.assertEqual(self.claims("Частота питания — 50 Гц."), [])

    def test_generic_frequency_not_confirmed_by_specific_limit(self):
        """Потерянный контекст не заменяется разрешением любого упоминания 1 кГц."""
        self.assertTrue(self.claims("Частота — 1 кГц."))

    def test_wrong_condition_rejected(self):
        """Нельзя незаметно заменить частоту в условии длительности импульса."""
        self.assertTrue(self.claims("Минимальная длительность импульса — 0.5 мс (скважность 2 для частоты 2 кГц)."))


if __name__ == "__main__":
    unittest.main()
