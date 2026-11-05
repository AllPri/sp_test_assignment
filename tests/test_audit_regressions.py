"""Воспроизводит ошибки аудита: извлечение, потерю конфликтов и подмену технических утверждений."""

import json
import os
import unittest
from unittest.mock import patch

from src.card.extraction import extract_text
from src.card.facts import prepare_facts
from src.card.validation import validate_card
from src.llm.providers import ModelSettings
from src.models import InputError, Product, parse_product
from src.sources.website import PageFacts
from src.workflow import run


def output_card(commercial):
    """Создаёт ответ правильного объёма с контролируемым техническим утверждением."""
    return {"seo_title": "Прибор", "seo_description": "Описание прибора для задач предприятия. " * 25,
            "search_queries": ["прибор", "выбрать прибор", "заказать прибор"], "commercial": commercial}


class ExtractionTests(unittest.TestCase):
    """Проверяет буквальную опору на источник и сохранение противоположных значений."""

    def test_description_becomes_characteristics_with_quotes(self):
        """Извлечённые значения и доказательства должны дословно присутствовать во входе."""
        text = "Питание 24 В; интерфейс RS-485."
        facts = prepare_facts(Product("Прибор", "Завод", description=text))
        self.assertEqual(facts["specs"], {"Питание": "24 В", "Интерфейс": "RS-485"})
        self.assertTrue(facts["enough"])
        for candidate in facts["extracted"]:
            self.assertIn(candidate["value"], candidate["excerpt"])
            self.assertIn(candidate["excerpt"], text)
            self.assertEqual(candidate["source"], "Входной JSON: description")

    def test_description_conflicts_with_structured_input(self):
        """Противоречие в свободном тексте не передаётся модели как ещё один допустимый факт."""
        facts = prepare_facts(Product("Прибор", "Завод", {"Питание": "24 В"}, "Питание прибора 220 В."))
        self.assertEqual(len(facts["conflicts"]), 1)
        self.assertNotIn("Питание", facts["specs"])
        self.assertFalse(facts["descriptions"])

    def test_power_synonyms_conflict(self):
        """Различные названия напряжения не скрывают конфликт с данными страницы."""
        facts = prepare_facts(Product("Прибор", specs={"Питание": "24 В"}),
                              PageFacts("source", specs={"Напряжение питания": "220 В"}))
        self.assertEqual(len(facts["conflicts"]), 1)

    def test_range_and_unit_in_label_not_false_conflict(self):
        """Единица в названии строки не должна создавать противоречие с тем же диапазоном в описании."""
        facts = prepare_facts(Product("ПМ01-24.АВ", specs={
            "Диапазон напряжений питания постоянного тока ПМ01-24.АВ, В": "от 10 до 30",
        }, description="Напряжение питания от 10 до 30 В."))
        self.assertFalse(facts["conflicts"])

    def test_negated_and_ambiguous_properties_not_extracted(self):
        """Отсутствие интерфейса и неразобранный выбор напряжения не становятся положительными фактами."""
        self.assertFalse(extract_text("Интерфейс RS-485 отсутствует.", "test"))
        self.assertFalse(extract_text("Питание 24 или 220 В.", "test"))

    def test_meaningless_input_is_insufficient(self):
        """Пунктуация и два идентификатора не заменяют техническое описание."""
        self.assertFalse(prepare_facts(Product("Прибор", description="?"))["enough"])
        self.assertFalse(prepare_facts(Product("Прибор", specs={"Артикул": "A", "Код товара": "B"}))["enough"])

    def test_unrecognized_description_requests_specs(self):
        """Неизвлечённые параметры не выдаются за готовый структурированный список."""
        facts = prepare_facts(Product("Прибор", "Завод", description="Устройство предназначено для контроля процессов на предприятии."))
        self.assertIn("Ключевые технические характеристики", facts["missing"])
        self.assertFalse(facts["enough"])


class IntegrityTests(unittest.TestCase):
    """Проверяет ошибки входа и связность технических значений в ответе модели."""

    def test_duplicate_keys_and_normalized_collisions_rejected(self):
        """Оба варианта молчаливой потери значения заканчиваются явной ошибкой."""
        for raw in ('{"name":"A","specs":{"Питание":"24 В","Питание":"220 В"}}',
                    '{"name":"A","specs":{"Питание":"24 В"," Питание ":"220 В"}}'):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                parse_product(raw)

    def test_swapped_values_rejected(self):
        """Одного наличия обоих чисел во входе недостаточно для подтверждения утверждения."""
        facts = prepare_facts(Product("Прибор", "Завод", {"Питание": "24 В", "Частота": "50 Гц"}))
        issues = validate_card(output_card("Питание 50 В, частота 24 Гц."), facts)
        self.assertTrue(any("характеристика" in issue for issue in issues))

    def test_unsupported_qualitative_properties_rejected(self):
        """Перечисленные в аудите свойства нельзя приписать без подтверждения."""
        facts = prepare_facts(Product("Прибор", "Завод", {"Питание": "24 В", "Частота": "50 Гц"}))
        issues = validate_card(output_card("Взрывозащищённый прибор с поддержкой Modbus и гальванической развязкой."), facts)
        self.assertTrue(any("свойство" in issue for issue in issues))

    def test_valid_field_value_pairs_allowed(self):
        """Корректные значения тех же параметров проходят проверку."""
        facts = prepare_facts(Product("Прибор", "Завод", {"Питание": "24 В", "Частота": "50 Гц"}))
        self.assertEqual(validate_card(output_card("Питание 24 В; частота 50 Гц."), facts), [])

    def test_terminal_punctuation_does_not_change_number(self):
        """Точка после обозначения IP20 не является новой характеристикой."""
        facts = prepare_facts(Product("Прибор", "Завод", {"Степень защиты": "IP20"}))
        self.assertEqual(validate_card(output_card("Степень защиты IP20."), facts), [])

    @patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_missing_data_does_not_require_api_key(self):
        """Недостаток фактов обнаруживается до авторизации и генерации."""
        state = run(json.dumps({"name": "Прибор"}), ModelSettings("OpenAI", "gpt-4.1"), False)
        self.assertEqual(state["status"], "insufficient_data")
        self.assertEqual(state["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
