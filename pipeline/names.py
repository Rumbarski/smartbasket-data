"""Нормализиране на имена, разфасовки и вериги от данните на КЗП."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Латински букви, които на касовите бележки и в КЗП се пишат вместо кирилски.
_LAT2CYR = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
})

_TRANSLIT = {
    "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ж": "zh", "З": "z",
    "И": "i", "Й": "y", "К": "k", "Л": "l", "М": "m", "Н": "n", "О": "o", "П": "p",
    "Р": "r", "С": "s", "Т": "t", "У": "u", "Ф": "f", "Х": "h", "Ц": "ts", "Ч": "ch",
    "Ш": "sh", "Щ": "sht", "Ъ": "a", "Ь": "y", "Ю": "yu", "Я": "ya",
}


def upper(s: str) -> str:
    """Главни букви, един интервал, десетична точка вместо запетая."""
    s = (s or "").upper().replace("Ё", "Е")
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    return re.sub(r"\s+", " ", s).strip()


def cyr(s: str) -> str:
    """Главни букви с латинските „двойници“ заменени с кирилица (за сравнения)."""
    return upper(s).translate(_LAT2CYR)


def slug(s: str) -> str:
    out = []
    for ch in upper(s):
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch.lower())
        else:
            out.append("-")
    return re.sub(r"-+", "-", "".join(out)).strip("-") or "x"


def short_hash(*parts: str, n: int = 8) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:n]


# ─── Вериги ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chain:
    id: str
    name: str


_KNOWN_CHAINS: list[tuple[str, str, str]] = [
    # (регулярен израз върху името на файла, id, показвано име)
    (r"ЛИДЛ|LIDL", "lidl", "Lidl"),
    (r"КАУФЛАНД|KAUFLAND", "kaufland", "Kaufland"),
    (r"БИЛЛА|БИЛА|BILLA", "billa", "Billa"),
    (r"ФАНТАСТИКО|FANTASTICO", "fantastico", "Fantastico"),
    (r"Т[\s-]?МАРКЕТ|T[\s-]?MARKET", "tmarket", "T Market"),
    (r"\bCBA\b|\bЦБА\b", "cba", "CBA"),
    (r"МЕТРО|METRO", "metro", "Metro"),
    (r"ПРО\s?МАРКЕТ|PRO\s?MARKET", "promarket", "ProMarket"),
    (r"EBAG|ЕБАГ", "ebag", "eBag"),
]


def chain_from_filename(filename: str) -> Chain:
    """„Лидл България_131071587.csv“ → Chain('lidl', 'Lidl')."""
    stem = re.sub(r"\.csv$", "", filename.rsplit("/", 1)[-1], flags=re.I)
    stem = re.sub(r"_\d+$", "", stem)  # ЕИК
    display = re.split(r"\s*\(", stem, maxsplit=1)[0].strip()
    probe = upper(stem)
    for pattern, cid, name in _KNOWN_CHAINS:
        if re.search(pattern, probe):
            return Chain(cid, name)
    return Chain(slug(display), display.title() if display.isupper() else display)


# ─── Обекти ──────────────────────────────────────────────────────────────────

def clean_store_label(label: str) -> str:
    """„114 - Габрово/ул. Свищовска 68“ → „Габрово, ул. Свищовска 68“."""
    s = re.sub(r"\s+", " ", (label or "")).strip()
    s = re.sub(r"^[A-Za-zА-Яа-я]{0,3}\d{1,5}\s*[-–—:.]\s*", "", s)  # код на обекта
    s = s.replace("/", ", ")
    s = re.sub(r"\s*,\s*", ", ", s).strip(" ,-")
    if s.isupper() and len(s) > 3:
        s = " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in s.split(" "))
    return s or (label or "").strip()


def store_id(chain_id: str, ekatte: str, label: str) -> str:
    return f"{chain_id}-{ekatte}-{short_hash(chain_id, ekatte, upper(label), n=6)}"


def ekatte_code(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits.zfill(5) if digits else ""


# ─── Продукти ────────────────────────────────────────────────────────────────

def product_key(code: str, name: str) -> str:
    """Стабилен ключ в рамките на веригата: кодът, ако го има, иначе хеш на името."""
    c = (code or "").strip()
    if c and not re.fullmatch(r"0+", c):
        return c
    return "n" + short_hash(upper(name), n=10)


_MASS = r"(?:КГ|KG|ГР?|GR?)"
_VOL = r"(?:МЛ|ML|MЛ|МL|Л|L|ЛТ|LT)"
_NUM = r"(\d+(?:\.\d+)?)"
_END = r"(?![А-ЯA-Z])"


@dataclass(frozen=True)
class Size:
    qty: float  # в `unit`
    unit: str  # 'kg' | 'l' | 'pcs'
    per_kg: bool = False  # цената е за 1 кг (продава се на тегло)


def _unit_value(num: str, unit: str) -> tuple[float, str]:
    v = float(num)
    u = unit.upper()
    if u in ("КГ", "KG"):
        return v, "kg"
    if u in ("Г", "ГР", "G", "GR"):
        return v / 1000, "kg"
    if u in ("Л", "L", "ЛТ", "LT"):
        return v, "l"
    return v / 1000, "l"  # мл


# Категории на КЗП, които обикновено се продават на тегло (цената е за кг).
WEIGHED_CATS = {8, 10, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 29, 30,
                50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61}


def parse_size(name: str, cat: int | None = None) -> Size | None:
    s = upper(name)
    # Мултипакет: „6Х1.5Л“, „2 X 5 КГ“.
    m = re.search(rf"(\d+)\s*[XХ×\*]\s*{_NUM}\s*({_MASS}|{_VOL}){_END}", s)
    if m:
        v, u = _unit_value(m.group(2), m.group(3))
        size = Size(round(int(m.group(1)) * v, 4), u)
    else:
        size = None
        found = [(float(n), u) for n, u in re.findall(rf"{_NUM}\s*({_MASS}|{_VOL})\.?{_END}", s)]
        if found:
            v, u = _unit_value(str(found[-1][0]), found[-1][1])
            size = Size(round(v, 4), u)
    if size is None and cat in (79, 80, 81, 82, 83, 84):
        # Козметика с отрязано „МЛ“: „П-ТА ЗА ЗЪБИ 75М“.
        m = re.search(r"(\d+)\s*[МM](?![А-ЯA-Z])", s)
        if m:
            size = Size(round(float(m.group(1)) / 1000, 4), "l")
    if size is None:
        # Яйца „М10“, „L10“; бройки „8БР“, „8 РОЛКИ“, „8Б“.
        m = re.search(r"\b[МMLЛ]\s?(\d{1,2})\b", s) if cat in (31, 32) else None
        if m:
            return Size(float(m.group(1)), "pcs")
        m = re.search(r"(\d+)\s*(?:БР|БРОЯ|PCS|РОЛКИ|РОЛ|Б)\.?(?![А-ЯA-Z])", s)
        if m:
            return Size(float(m.group(1)), "pcs")
    weighed = cat in WEIGHED_CATS
    if size is not None and size.unit == "kg" and weighed and size.qty >= 2:
        return Size(1.0, "kg", per_kg=True)  # насипно: „/ 8КГ/“ е опаковката на склада
    if size is None and (re.search(r"(^|[\s/.(])(КГ|KG)([\s/.)]|$)", s) or re.search(r"\bНА КГ\b", s)):
        return Size(1.0, "kg", per_kg=True)
    if size is None and weighed:
        return Size(1.0, "kg", per_kg=True)
    return size


def parse_fat(name: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", upper(name))
    if not m:
        return None
    v = float(m.group(1))
    return v if v <= 45 else None
