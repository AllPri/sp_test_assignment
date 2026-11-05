"""Объединяет подтверждённые факты и отделяет конфликты от данных для модели."""

from dataclasses import asdict
import re

from .extraction import extract_descriptions
from .normalization import comparable, field_key


def prepare_facts(product, page=None, *, extracted=None):
    """Сохраняет оба спорных значения, но ни одно не передаёт в генерацию."""
    groups = {}
    for name, value in product.specs.items():
        groups.setdefault(field_key(name), []).append((name, value, "Входной JSON", f"{name}: {value}"))
    if page:
        for name, value in page.specs.items():
            groups.setdefault(field_key(name), []).append((name, value, page.url, page.evidence.get(name, f"{name}: {value}")))
    extracted = extract_descriptions(product, page) if extracted is None else extracted
    for fact in extracted:
        groups.setdefault(field_key(fact["name"]), []).append(
            (fact["name"], fact["value"], fact["source"], fact["excerpt"]))
    specs, conflicts, added, provenance, missing = {}, list(page.conflicts) if page else [], [], {}, []
    blocked = {field_key(c["field"]) for c in conflicts}
    for key, entries in groups.items():
        if key in blocked:
            missing.append(entries[0][0] + " — конфликт на странице")
            continue
        populated = [(n, v, s, e) for n, v, s, e in entries if v.strip()]
        if len({comparable(n, v) for n, v, _, _ in populated}) > 1:
            conflicts.append({"field": entries[0][0], "values": [
                {"value": v, "source": s, "excerpt": e} for _, v, s, e in populated
            ]})
            missing.append(entries[0][0] + " — конфликт значений")
            continue
        if not populated:
            specs[entries[0][0]] = "данных нет"
            missing.append(entries[0][0])
            continue
        name, value, source, _ = populated[0]
        specs[name] = value
        provenance[name] = [{"source": s, "excerpt": e} for _, _, s, e in populated]
        if not source.startswith("Входной JSON"):
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
    useful_description = any(
        len(item["text"].split()) >= 6 and re.search(
            r"предназнач|измер|контрол|сбор|сбора|обмен|передач|регулир", item["text"], re.I)
        for item in descriptions)
    if not useful_description:
        missing.append("Подтверждённое описание назначения")
    metadata = {"артикул", "кодтовара", "sku", "vendorcode", "цена", "наличие"}
    usable = {k: v for k, v in specs.items() if v != "данных нет" and field_key(k) not in metadata}
    if not usable:
        missing.append("Ключевые технические характеристики")
    enough = len(usable) >= 2 or (useful_description and bool(usable))
    return {
        "name": product.name, "manufacturer": product.manufacturer or "данных нет",
        "specs": specs, "descriptions": descriptions, "missing": missing,
        "conflicts": conflicts, "added": added, "provenance": provenance,
        "warnings": warnings, "enough": enough,
        "source_page": asdict(page) if page else None,
        "extracted": extracted,
    }
