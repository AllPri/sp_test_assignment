"""Проверяет связи распознаваемых характеристик с их значениями и отдельные технические обещания."""

import re

from .extraction import NEGATIVE, extract_text, sentence_at
from .normalization import comparable, field_key


PROPERTIES = {
    "взрывозащита": r"взрывозащищ\w*|взрывозащит\w*",
    "гальваническая развязка": r"гальваническ\w*\s+развяз\w*",
    "коррозионная стойкость": r"коррозионностойк\w*",
    "протокол Modbus": r"\bmodbus\b",
}


def positive_properties(text):
    """Не считает отрицание свойства подтверждением его наличия."""
    found = set()
    for name, pattern in PROPERTIES.items():
        for match in re.finditer(pattern, text, re.I):
            if not NEGATIVE.search(sentence_at(text, match.start(), match.end())):
                found.add(name)
    return found


def check_claims(card, facts):
    """Ловит подмену поля или единицы у известных параметров; не заменяет проверку всего текста человеком."""
    known = {}
    allowed_properties = set()
    for name, value in facts["specs"].items():
        if value != "данных нет":
            known.setdefault(field_key(name), set()).add(comparable(name, value))
            allowed_properties.update(positive_properties(name + ": " + value))
            # Условие в скобках сверяем с тем же условием исходной технической строки.
            for condition in extract_text(name + ": " + value, "Характеристики", include_custom=False):
                if condition["name"] == "Частота в условии длительности импульса":
                    known.setdefault(field_key(condition["name"]), set()).add(
                        comparable(condition["name"], condition["value"]))
    for description in facts["descriptions"]:
        allowed_properties.update(positive_properties(description["text"]))
        for fact in extract_text(description["text"], description["source"]):
            known.setdefault(field_key(fact["name"]), set()).add(comparable(fact["name"], fact["value"]))
    text = "\n".join([card["seo_title"], card["seo_description"], card["commercial"], *card["search_queries"]])
    issues = []
    for claim in extract_text(text, "Ответ модели", include_custom=False):
        if comparable(claim["name"], claim["value"]) not in known.get(field_key(claim["name"]), set()):
            issues.append(f"Не подтверждена характеристика в тексте: {claim['name']} = {claim['value']}.")
    unsupported = positive_properties(text) - allowed_properties
    issues += ["Не подтверждено техническое свойство: " + name + "." for name in sorted(unsupported)]
    return list(dict.fromkeys(issues))
