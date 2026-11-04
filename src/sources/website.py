"""Извлекает сведения со страниц заказчика, сохраняя неоднозначность модификаций."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from ..models import ServiceError
from ..transport import request_bytes


def compact(text):
    """Сравнивает обозначения без различий регистра, пробелов и вида дефиса."""
    return re.sub(r"[\s–—−-]+", "", text.casefold())


def contains_name(name, text):
    """Не считает ПРИБОР-24 совпадением с ПРИБОР-240 или ПРИБОР-24.АВ."""
    needle = re.sub(r"[–—−]", "-", name.casefold().strip())
    haystack = re.sub(r"[–—−]", "-", text.casefold())
    pattern = re.escape(needle).replace(r"\ ", r"\s*")
    return bool(needle) and re.search(r"(?<!\w)" + pattern + r"(?![\w.])", haystack) is not None


@dataclass
class PageFacts:
    """Возвращает факты отдельно от предупреждений и исходных фрагментов."""

    url: str
    title: str = ""
    description: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)


class ProductHTML(HTMLParser):
    """Читает заголовки, раздел описания и таблицы без меню, скриптов и отзывов."""

    def __init__(self):
        """Создаёт независимый разборщик для одной страницы."""
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.heading_tag = ""
        self.heading = []
        self.section = ""
        self.description = []
        self.rows = []
        self.row = None
        self.cell = None
        self.hidden = 0
        self.all_headings = []

    def handle_starttag(self, tag, attrs):
        """Выделяет границы заголовков и ячеек; активное содержимое пропускает."""
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if self.hidden:
            return
        if tag in ("h1", "h2", "h3"):
            self.heading_tag, self.heading = tag, []
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
        if tag in ("br", "p", "li"):
            if self.cell is not None:
                self.cell.append(" ")
            if self.section == "description":
                self.description.append("\n")

    def handle_data(self, data):
        """Собирает только текст нужных разделов, сохраняя границы фрагментов."""
        if self.hidden:
            return
        if self.heading_tag:
            self.heading.append(data)
        if self.cell is not None:
            self.cell.append(data)
        if self.section == "description" and not self.heading_tag:
            self.description.append(data)

    def handle_endtag(self, tag):
        """Завершает раздел при следующем h2, чтобы не захватить соседние товары."""
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag == self.heading_tag:
            text = " ".join("".join(self.heading).split())
            self.all_headings.append(text)
            if tag == "h1" and not self.title:
                self.title = text
            if tag == "h2":
                lowered = text.casefold()
                self.section = ""
                if lowered.startswith("описание "):
                    self.section = "description"
                if lowered.startswith(("характеристики ", "параметры дискретных")):
                    self.section = "specs"
            self.heading_tag = ""
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            if len(self.row) == 2 and self.section == "specs":
                self.rows.append(tuple(self.row))
            self.row = None


def parse_page(html, product):
    """Не переносит общие сведения серии в исполнение без точного совпадения заголовка."""
    parser = ProductHTML()
    parser.feed(html)
    facts = PageFacts(url=product.url, title=parser.title)
    exact = contains_name(product.name, parser.title)
    maker_matches = bool(product.manufacturer) and compact(product.manufacturer) in compact(parser.title)
    if not exact or not maker_matches:
        facts.warnings.append(
            "Заголовок страницы не подтверждает точное исполнение и производителя. "
            "Общее описание и общие характеристики не добавлены."
        )
    revisions = any("отличия" in h.casefold() or "версии" in h.casefold()
                    for h in parser.all_headings)
    if revisions:
        facts.warnings.append("На странице сравниваются версии. Описание не добавлено; проверьте исполнение.")
    if exact and maker_matches and not revisions:
        facts.description = " ".join("".join(parser.description).split())[:12_000]
    ambiguous = set()
    for label, value in parser.rows:
        if not label or not value or label.casefold() in ("наименование", "наименование параметра"):
            continue
        if value in ("-", "—", "–"):
            continue
        if revisions and any(word in label.casefold() for word in ("протокол", "памят", "конфигур")):
            facts.warnings.append(f"Зависящая от версии характеристика не добавлена: {label}")
            continue
        identifiers = set(re.findall(r"[А-ЯA-Z]{2,}\d*[-–]\d[\w.()-]*", label, re.I))
        specific = contains_name(product.name, label)
        if len(identifiers) > 1 or "*" in value or "в зависимости" in value.casefold():
            facts.warnings.append(f"Неоднозначная строка не добавлена: {label}")
            continue
        if identifiers and not specific:
            continue
        if not (exact and maker_matches) and not (specific and maker_matches):
            continue
        name = label.rstrip(":")
        if name in ambiguous:
            continue
        if name in facts.specs and facts.specs[name] != value:
            facts.conflicts.append({"field": name, "values": [
                {"value": facts.specs[name], "source": product.url},
                {"value": value, "source": product.url},
            ]})
            ambiguous.add(name)
            facts.specs.pop(name)
            facts.evidence.pop(name)
            facts.warnings.append(f"На странице разные значения одной характеристики: {name}; не добавлено.")
            continue
        facts.specs[name] = value
        facts.evidence[name] = f"{label}: {value}"
    if not facts.description and not facts.specs:
        facts.warnings.append("Применимые сведения не найдены. Используются только входные данные.")
    return facts


def fetch_page(product):
    """Загружает только карточки souz-pribor.ru без перенаправлений и посторонних URL."""
    try:
        parsed = urlsplit(product.url)
        valid = (
            parsed.scheme == "https" and parsed.hostname in ("www.souz-pribor.ru", "souz-pribor.ru")
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and parsed.path.startswith("/product/") and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ServiceError("Для дообогащения нужна HTTPS-ссылка /product/ на сайте souz-pribor.ru.")
    raw, headers = request_bytes(
        product.url, headers={"User-Agent": "ProductDraftPrototype/1.0"}, timeout=15,
    )
    if "text/html" not in headers.get("Content-Type", "").lower():
        raise ServiceError("По ссылке получена не HTML-страница товара.")
    try:
        html = raw.decode(headers.get_content_charset() or "utf-8")
    except (UnicodeError, LookupError):
        raise ServiceError("Не удалось прочитать кодировку страницы.") from None
    return parse_page(html, product)
