"""Объединяет подтверждённые факты и отделяет конфликты от данных для модели."""

from dataclasses import asdict
import re


ALIASES = {
    "интерфейссвязискомпьютером": "интерфейс",
    "типинтерфейса": "интерфейс",
    "интерфейссвязи": "интерфейс",
    "количестводискретныхвходов": "числовходов",
    "колвовходныхканалов": "числовходов",
    "количестводискретныхвыходныхэлементов": "числовыходов",
    "колвовыходныхканалов": "числовыходов",
    "степеньзащиты": "степеньзащитыкорпуса",
}


def field_key(name):
    """Сводит известные названия одной характеристики к общему ключу."""
    key = re.sub(r"[^\w]", "", name.casefold().replace("ё", "е"))
    return ALIASES.get(key, key)


def value_key(value):
    """Игнорирует только запись пробелов и дефисов; единицы измерения не пересчитывает."""
    return re.sub(r"\s+", "", value.casefold().replace("–", "-").replace("−", "-"))


def prepare_facts(product, page=None):
    """Сохраняет оба спорных значения, но ни одно не передаёт в генерацию."""
    groups = {}
    for name, value in product.specs.items():
        groups.setdefault(field_key(name), []).append((name, value, "Входной JSON"))
    if page:
        for name, value in page.specs.items():
            groups.setdefault(field_key(name), []).append((name, value, page.url))
    specs, conflicts, added, provenance, missing = {}, list(page.conflicts) if page else [], [], {}, []
    blocked = {field_key(c["field"]) for c in conflicts}
    for key, entries in groups.items():
        if key in blocked:
            missing.append(entries[0][0] + " — конфликт на странице")
            continue
        populated = [(n, v, s) for n, v, s in entries if v.strip()]
        if len({value_key(v) for _, v, _ in populated}) > 1:
            conflicts.append({"field": entries[0][0], "values": [
                {"value": v, "source": s} for _, v, s in populated
            ]})
            missing.append(entries[0][0] + " — конфликт значений")
            continue
        if not populated:
            specs[entries[0][0]] = "данных нет"
            missing.append(entries[0][0])
            continue
        name, value, source = populated[0]
        specs[name] = value
        provenance[name] = [{"source": s, "excerpt": f"{n}: {v}"} for n, v, s in populated]
        if source != "Входной JSON":
            added.append({"field": name, "value": value, "source": source})
    if not product.manufacturer:
        missing.append("Производитель")
    # Свободный текст нельзя надёжно очистить от конфликтующего факта: исключаем целиком.
    descriptions = []
    warnings = list(page.warnings) if page else []
    if conflicts:
        warnings.append("Из-за конфликтов свободные описания исключены из запроса к модели.")
    else:
        if product.description:
            descriptions.append({"source": "Входной JSON", "text": product.description})
        if page and page.description:
            descriptions.append({"source": page.url, "text": page.description})
            added.append({"field": "Описание", "value": page.description, "source": page.url})
    if not descriptions:
        missing.append("Подтверждённое описание назначения")
    usable = {k: v for k, v in specs.items() if v != "данных нет"}
    enough = bool(descriptions or len(usable) >= 2)
    return {
        "name": product.name, "manufacturer": product.manufacturer or "данных нет",
        "specs": specs, "descriptions": descriptions, "missing": missing,
        "conflicts": conflicts, "added": added, "provenance": provenance,
        "warnings": warnings, "enough": enough,
        "source_page": asdict(page) if page else None,
    }
