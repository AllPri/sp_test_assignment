"""Проверяет измеримые ограничения; не выдаёт проверку формата за проверку всех фактов."""

import json
import re

from .claims import check_claims


def numeric_tokens(text):
    """Находит числа и обозначения с цифрами, чтобы заметить добавленные моделью значения."""
    return {token.rstrip(".,") for token in re.findall(r"[\w]*\d[\w.,/–—−-]*", text.casefold())}


def validate_card(card, facts):
    """Проверяет длины, поисковые фразы и новые числа во всех текстовых разделах."""
    issues = []
    if len(card["seo_title"]) > 70:
        issues.append(f"Заголовок: {len(card['seo_title'])} символов, нужно не более 70.")
    length = len(card["seo_description"])
    if not 800 <= length <= 1200:
        issues.append(f"Описание: {length} символов, нужно от 800 до 1200.")
    queries = card["search_queries"]
    if not 3 <= len(queries) <= 5:
        issues.append("Нужно 3–5 поисковых запросов.")
    if len({q.casefold() for q in queries}) != len(queries):
        issues.append("Поисковые запросы не должны повторяться.")
    allowed = {key: facts[key] for key in ("name", "manufacturer", "specs", "descriptions")}
    known = numeric_tokens(json.dumps(allowed, ensure_ascii=False))
    output = " ".join([card["seo_title"], card["seo_description"], card["commercial"], *queries])
    added = numeric_tokens(output) - known
    if added:
        issues.append("Неподтверждённые числовые обозначения: " + ", ".join(sorted(added)))
    issues.extend(check_claims(card, facts))
    return issues
