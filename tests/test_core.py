"""Проверяет вход, конфликты и ограничения без установки пакетов и вызова моделей."""

import json
import unittest

from src.card.export import json_report, markdown
from src.card.facts import prepare_facts
from src.models import InputError, Product, decode_card, parse_product
from src.card.prompts import build_prompt
from src.card.validation import validate_card
from src.sources.website import PageFacts


def valid_card():
    """Даёт текст нужной длины для проверки ограничений, не имитируя реальную генерацию."""
    return {"seo_title": "Тестовый прибор", "seo_description": "Подтверждённое описание прибора. " * 30,
            "search_queries": ["прибор", "заказать прибор", "прибор для предприятия"],
            "commercial": "Для задач, указанных во входных данных."}


class InputTests(unittest.TestCase):
    """Проверяет отказ до внешних действий и явную обработку пустых данных."""

    def test_bad_inputs(self):
        """Некорректные структуры не превращаются молча в пустой товар."""
        for raw in ("", "{", "[]", "null", '{"name":""}', '{"name":123}',
                    '{"name":"A","specs":[]}', '{"name":"A","specs":{"x":null}}',
                    '{"name":"A","unknown":1}', '{"name":"A","specs":{"x":true}}',
                    '{"name":"A","specs":{"x":NaN}}'):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                parse_product(raw)

    def test_missing_fields_remain_missing(self):
        """Одного названия недостаточно для содержательной генерации."""
        facts = prepare_facts(parse_product('{"name":"A", "specs":{"Питание":""}}'))
        self.assertFalse(facts["enough"])
        self.assertEqual(facts["specs"]["Питание"], "данных нет")
        self.assertIn("Производитель", facts["missing"])


class ConflictTests(unittest.TestCase):
    """Проверяет исключение противоречий из промпта и сохранение их в экспорте."""

    def test_conflict_removed_from_every_model_source(self):
        """Свободный текст со спорными значениями тоже не должен просочиться в запрос."""
        product = Product("Прибор", "Завод", {"Интерфейс": "RS-232"}, "Интерфейс RS-232")
        page = PageFacts("https://www.souz-pribor.ru/product/a/", description="RS-485",
                         specs={"Интерфейс связи с компьютером": "RS-485"})
        facts = prepare_facts(product, page)
        prompt = build_prompt(facts)
        self.assertNotIn("RS-232", prompt)
        self.assertNotIn("RS-485", prompt)
        self.assertEqual(len(facts["conflicts"]), 1)
        self.assertEqual({v["value"] for v in facts["conflicts"][0]["values"]}, {"RS-232", "RS-485"})
        state = {"status": "insufficient_data", "facts": facts}
        for output in (markdown(state), json_report(state)):
            self.assertIn("RS-232", output)
            self.assertIn("RS-485", output)
            self.assertIn(page.url, output)

    def test_enrichment_fills_empty_value(self):
        """Сайт может заполнить пустое поле, сохранив источник дополнения."""
        facts = prepare_facts(Product("A", specs={"Питание": ""}),
                              PageFacts("url", specs={"Питание": "24 В"}))
        self.assertEqual(facts["specs"]["Питание"], "24 В")
        self.assertEqual(facts["added"][0]["source"], "url")

    def test_equivalent_typography_is_not_conflict(self):
        """Различия пробелов не должны блокировать одно и то же значение."""
        facts = prepare_facts(Product("A", specs={"Интерфейс": "RS-485"}),
                              PageFacts("url", specs={"Тип интерфейса": "RS-485 "}))
        self.assertFalse(facts["conflicts"])

    def test_internal_alias_conflict(self):
        """Противоречие может возникнуть и внутри одного JSON."""
        facts = prepare_facts(Product("A", specs={"Интерфейс": "A", "Тип интерфейса": "B"}))
        self.assertEqual(len(facts["conflicts"]), 1)
        self.assertFalse(facts["specs"])


class OutputTests(unittest.TestCase):
    """Проверяет формат, длины и неподтверждённые числовые характеристики."""

    def setUp(self):
        """Готовит один подтверждённый факт для каждой независимой проверки."""
        self.facts = prepare_facts(Product("Прибор", "Завод", {"Питание": "24 В"}))

    def test_valid_card(self):
        """Ответ подходящей формы проходит только заявленные формальные проверки."""
        card = decode_card(json.dumps(valid_card()))
        self.assertEqual(validate_card(card, self.facts), [])

    def test_invalid_model_json(self):
        """Ошибочный JSON и лишние поля требуют доработки."""
        for raw in ("{", "[]", "{}", json.dumps({**valid_card(), "specs": {}})):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_card(raw)

    def test_length_queries_and_new_numbers(self):
        """Проверяет одновременно независимые нарушения в разных разделах."""
        card = valid_card()
        card.update(seo_title="А" * 71, seo_description="Коротко", search_queries=["a", "a"],
                    commercial="Работает от 220 В")
        issues = validate_card(card, self.facts)
        self.assertEqual(len(issues), 5)
        self.assertTrue(any("220" in item for item in issues))

    def test_known_number_allowed(self):
        """Подтверждённое напряжение разрешено в тексте карточки."""
        card = valid_card()
        card["commercial"] = "Питание 24 В"
        self.assertEqual(validate_card(card, self.facts), [])


if __name__ == "__main__":
    unittest.main()
