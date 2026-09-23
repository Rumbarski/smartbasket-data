"""Съпоставяне на продуктите от КЗП с общия каталог на приложението (SKU).

Всеки SKU е „родово“ изделие като „Прясно мляко 3.6% 1 л“. За всеки обект
търсим най-евтиния подходящ продукт от веригата и смятаме цена за размера
на SKU-то (по цена за кг/л/бр). Ако разфасовката се различава с над 12%,
цената е „приблизителна“ (approx).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .names import Size, cyr, parse_fat, parse_size

PLAIN_DAIRY_EXCLUDE = r"АЦИДОФИЛ|БЕЗ ?ЛАКТОЗ|БЕЗЛАКТОЗ|ГРЪЦК|ОВЧ|КОЗ|БИВОЛ|ПЛОД|ЯГОД|ВАНИЛ|ШОКОЛАД|КАКАО|ПРОБИОТ|ЛИМЕЦ"


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    cats: frozenset[int]
    size: float  # в `unit`
    unit: str  # 'kg' | 'l' | 'pcs'
    include: str | None = None
    exclude: str | None = None
    fat: tuple[float, float] | None = None
    default_size: float | None = None  # когато в името няма разфасовка


def _r(id, name, cats, size, unit, **kw) -> Rule:
    return Rule(id, name, frozenset(cats), size, unit, **kw)


RULES: list[Rule] = [
    _r("milk36", "Прясно мляко 3.6% 1 л", {6}, 1, "l", fat=(3.5, 3.7), default_size=1,
       exclude=PLAIN_DAIRY_EXCLUDE),
    _r("milk15", "Прясно мляко 1.5% 1 л", {6}, 1, "l", fat=(1.4, 1.6), default_size=1,
       exclude=PLAIN_DAIRY_EXCLUDE),
    _r("yog36", "Кисело мляко 3.6% 400 г", {7}, 0.4, "kg", fat=(3.5, 3.7), default_size=0.4,
       exclude=PLAIN_DAIRY_EXCLUDE),
    _r("yog2", "Кисело мляко 2% 400 г", {7}, 0.4, "kg", fat=(1.8, 2.2), default_size=0.4,
       exclude=PLAIN_DAIRY_EXCLUDE),
    _r("cheese", "Сирене краве 400 г", {9, 8}, 0.4, "kg", include=r"КРАВ",
       exclude=PLAIN_DAIRY_EXCLUDE + r"|ПИКАНТ|ЧУШ|ДОМАТ|МАСЛИН|БИЛК|ЧЕСЪН|ЛЮТ"),
    _r("kashkaval", "Кашкавал краве 400 г", {11, 10}, 0.4, "kg", include=r"КРАВ",
       exclude=PLAIN_DAIRY_EXCLUDE + r"|ПУШЕН|МАНАТАР|ЧУШ|БИЛК|ЧЕСЪН|ЛЮТ"),
    _r("butter", "Масло краве 250 г", {12}, 0.25, "kg", exclude=r"БЕЗ ?ЛАКТОЗ|КОЗ|ОВЧ|ЧЕСЪН|БИЛК"),
    _r("eggs", "Яйца M, 10 бр.", {31}, 10, "pcs", default_size=10),
    _r("bread", "Хляб пълнозърнест 500 г", {3}, 0.5, "kg"),
    _r("breadDob", "Хляб „Добруджа“ 650 г", {2}, 0.65, "kg"),
    _r("banana", "Банани", {52}, 1, "kg"),
    _r("tomato", "Домати", {54}, 1, "kg", exclude=r"ЧЕРИ|ШЕРИ"),
    _r("cucumber", "Краставици", {58}, 1, "kg"),
    _r("potato", "Картофи", {61}, 1, "kg", exclude=r"СЛАДК|БАТАТ"),
    _r("onion", "Лук кромид", {55}, 1, "kg", exclude=r"ЗЕЛЕН|ПРАЗ|ЧЕРВЕН"),
    _r("carrot", "Моркови", {56}, 1, "kg"),
    _r("apple", "Ябълки", {53}, 1, "kg"),
    _r("lemons", "Лимони", {50}, 1, "kg"),
    _r("oranges", "Портокали", {51}, 1, "kg"),
    _r("cabbage", "Зеле", {57}, 1, "kg", exclude=r"ЧЕРВЕН|КИСЕЛ"),
    _r("chFillet", "Пилешко филе охладено 1 кг", {16}, 1, "kg", exclude=r"ПАНИР|МАРИН"),
    _r("chLegs", "Пилешки бутчета 1 кг", {17}, 1, "kg", exclude=r"ПАНИР|МАРИН"),
    _r("chWhole", "Пиле цяло", {15}, 1, "kg"),
    _r("mince", "Кайма смес 500 г", {25}, 0.5, "kg"),
    _r("mackerel", "Скумрия замразена", {29}, 1, "kg", include=r"СКУМРИ"),
    _r("oil", "Олио слънчогледово 1 л", {42}, 1, "l", default_size=1),
    _r("rice", "Ориз 1 кг", {35}, 1, "kg",
       exclude=r"АРБОРИО|БАСМАТИ|ЖАСМИН|ДИВ|КАФЯВ|ЧЕРВЕН|ЧЕР |ПЪЛНОЗ|ПАРБОЙЛД|ВАРЕН|ТОРБИЧК"),
    _r("beans", "Боб зрял 1 кг", {33}, 1, "kg", default_size=1),
    _r("lentils", "Леща 1 кг", {34}, 1, "kg", default_size=1),
    _r("pasta", "Спагети 500 г", {37}, 0.5, "kg", default_size=0.5, exclude=r"ПЪЛНОЗ|БЕЗ ГЛУТЕН"),
    _r("macaroni", "Макарони 500 г", {36}, 0.5, "kg", include=r"МАКАРОН|ПЕНЕ|ФУЗИЛИ|ФАРФАЛ|РИГАТОН",
       exclude=r"ПЪЛНОЗ|БЕЗ ГЛУТЕН|ЛАЗАН|КУС|ТАЛИАТ|ЮФКА|ТОРТЕЛ|ДЕТСК"),
    _r("flour", "Брашно тип 500, 1 кг", {40}, 1, "kg", default_size=1, exclude=r"ПЪЛНОЗ|ЛИМЕЦ|РЪЖ"),
    _r("sugar", "Захар 1 кг", {38}, 1, "kg", default_size=1, exclude=r"КАФЯВ|ПУДРА|ТРЪСТИК|ВАНИЛ"),
    _r("salt", "Сол 1 кг", {39}, 1, "kg", default_size=1),
    _r("tomCan", "Домати консерва 400 г", {48}, 0.4, "kg", include=r"БЕЛЕН|НАРЯЗ|КУБЧ|ПАСИР",
       exclude=r"ПЮРЕ|ПАСТА|КЕТЧУП|СОС"),
    _r("coffee", "Кафе мляно 225 г", {70}, 0.225, "kg", exclude=r"БЕЗ КОФЕИН|ДЕКАФ|КАПСУЛ"),
    _r("water15", "Минерална вода 1.5 л", {73}, 1.5, "l"),
    _r("toilet", "Тоалетна хартия 8 ролки", {85}, 8, "pcs", default_size=8),
    _r("paste", "Паста за зъби 75 мл", {81}, 0.075, "l"),
    _r("dish", "Препарат за съдове 500 мл", {79}, 0.5, "l"),
]

RULES_BY_ID = {r.id: r for r in RULES}
TOLERANCE = 0.12


@dataclass(frozen=True)
class Fit:
    """Как един продукт пасва на SKU: колко от SKU-то е една опаковка."""

    sku: str
    factor: float  # цена_за_SKU = цена_на_опаковката * factor
    approx: bool


def _size_for(rule: Rule, name: str, cat: int) -> tuple[Size | None, bool]:
    size = parse_size(name, cat)
    if size is None and rule.default_size is not None:
        return Size(rule.default_size, rule.unit), True
    return size, False


def fits(name: str, cat: int) -> list[Fit]:
    """Кои SKU-та покрива даден продукт на КЗП (обикновено 0 или 1)."""
    out: list[Fit] = []
    text = cyr(name)
    fat = None
    for rule in RULES:
        if cat not in rule.cats:
            continue
        if rule.include and not re.search(rule.include, text):
            continue
        if rule.exclude and re.search(rule.exclude, text):
            continue
        if rule.fat is not None:
            fat = parse_fat(name) if fat is None else fat
            if fat is None or not (rule.fat[0] <= fat <= rule.fat[1]):
                continue
        size, assumed = _size_for(rule, name, cat)
        if size is None or size.unit != rule.unit or size.qty <= 0:
            continue
        # На тегло: цената е за 1 кг, а SKU-то може да е 0.5 кг.
        factor = rule.size / size.qty
        off = abs(size.qty - rule.size) / rule.size
        approx = assumed or (off > TOLERANCE and not size.per_kg) or (size.per_kg and rule.size != 1)
        out.append(Fit(rule.id, round(factor, 6), approx))
    return out
