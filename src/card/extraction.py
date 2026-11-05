"""Извлекает явно записанные характеристики вместе с дословными доказательствами."""

import re

from .normalization import field_key


NUMBER = r"[+-]?\d+(?:[.,]\d+)?"
RANGE = rf"(?:от\s*)?{NUMBER}(?:\s*(?:до|[–—−…-]|\.\.)\s*{NUMBER})?"
PATTERNS = (
    ("Питание", rf"(?:напряжени[ея]\s+питания|питани[ея])\s*(?:прибора\s*)?[:=—–-]?\s*({RANGE}\s*(?:В|V)(?!\w))"),
    ("Интерфейс", r"интерфейс(?:ы|а|ом)?\s*(?:связи\s*)?[:—–-]?\s*((?:RS[-– ]?(?:232|485|422))(?:\s*[/,]\s*RS[-– ]?(?:232|485|422))*)"),
    ("Степень защиты", r"(?:степень\s+защиты(?:\s+корпуса)?|защита\s+корпуса)\s*[:—–-]?\s*(IP\s*\d{2}(?!\d))"),
    ("Класс точности", rf"класс\s+точности\s*[:—–-]?\s*({NUMBER})"),
    ("Максимальная частота входного сигнала", rf"максимальная\s+частота\s+(?:входного\s+сигнала|сигнала,?\s+подаваемого\s+на\s+дискретный\s+вход,?)\s*[:—–-]?\s*({RANGE}\s*(?:кГц|МГц|Гц|Hz)(?!\w))"),
    ("Частота питания", rf"частота\s+питания\s*[:—–-]?\s*({RANGE}\s*(?:кГц|МГц|Гц|Hz)(?!\w))"),
    ("Частота", rf"частот[аы]\s*[:—–-]?\s*({RANGE}\s*(?:кГц|МГц|Гц|Hz)(?!\w))"),
    ("Диапазон измерений", rf"диапазон\s+измерени[йя]\s*[:—–-]?\s*({RANGE}\s*(?:МПа|кПа|Па|бар|bar|°\s*C|°\s*С|мм|мА)(?!\w))"),
    ("Количество дискретных входов", r"(?:количество\s+(?:дискретных\s+)?входов|число\s+входов)\s*[:—–-]?\s*(\d+)(?!\d)"),
    ("Количество дискретных выходных элементов", r"(?:количество\s+(?:дискретных\s+)?выходов|число\s+выходов)\s*[:—–-]?\s*(\d+)(?!\d)"),
)
NEGATIVE = re.compile(r"\b(?:нет|без|отсутств\w*|не\s+(?:поддерж\w*|име\w*|предусмотр\w*))\b", re.I)


def sentence_at(text, start, end):
    """Берёт ближайшую фразу, не разрезая десятичные числа по точке."""
    boundaries = list(re.finditer(r"[;\n]|\.(?=\s|$)", text))
    left = max((m.end() for m in boundaries if m.end() <= start), default=0)
    right = min((m.start() for m in boundaries if m.start() >= end), default=len(text))
    return text[left:right].strip()


def extract_text(text, source, *, include_custom=True):
    """Принимает только распознаваемые пары; значение и доказательство буквально присутствуют в тексте."""
    found = []
    for name, pattern in PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            excerpt = sentence_at(text, match.start(), match.end())
            if NEGATIVE.search(excerpt):
                continue
            value = match.group(1).strip()
            if not value or value not in excerpt or excerpt not in text:
                continue
            field_name = name
            # Частота в скобках описывает условие измерения длительности, а не отдельный режим прибора.
            if name == "Частота" and re.search(r"для\s*$", text[:match.start()], re.I):
                if re.search(r"длительност\w*.*импульс|скважност", excerpt, re.I):
                    field_name = "Частота в условии длительности импульса"
            found.append({"name": field_name, "value": value, "source": source, "excerpt": excerpt})
    # Явные строки «название: значение» поддерживают и редкие технические параметры.
    for fragment in re.split(r"[;\n]", text) if include_custom else []:
        match = re.fullmatch(r"\s*([А-Яа-яЁё][А-Яа-яЁё /()\-]{2,60}):\s*(.{1,180}?)\s*", fragment)
        if match and not NEGATIVE.search(fragment):
            name, value = match.groups()
            if any(field_key(f["name"]) == field_key(name) for f in found):
                continue
            value = value.rstrip(". ")
            excerpt = fragment.strip()
            if not any(f["value"] == value and f["excerpt"] == excerpt for f in found):
                found.append({"name": name.strip(), "value": value.strip(), "source": source, "excerpt": excerpt})
    return found


def extract_descriptions(product, page=None):
    """Обрабатывает только исходное описание и допущенное описание выбранного исполнения со страницы."""
    sources = [(product.description, "Входной JSON: description")]
    if page and page.description:
        sources.append((page.description, page.url))
    facts = [fact for text, source in sources if text for fact in extract_text(text, source)]
    return facts
