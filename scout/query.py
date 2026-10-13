"""Rule-based parser for free-text requests like
"молочка в екб с декларациями, заказ 30 кг в неделю" -> structured filters.
Deterministic and instant; an LLM can replace it behind the same interface."""

import re
from dataclasses import dataclass, field

from scout.taxonomy import CATEGORIES, CITIES

ALIASES = {
    'молочка': 'dairy', 'сыры': 'dairy', 'мясо': 'meat', 'курица': 'meat', 'рыба': 'fish', 'морепродукты': 'fish',
    'овощи': 'veg', 'фрукты': 'veg', 'зелень': 'veg', 'бакалея': 'grocery', 'заморозка': 'grocery',
    'суши': 'asian', 'японская': 'asian', 'азиатская': 'asian', 'напитки': 'drinks', 'кофе': 'drinks',
    'упаковка': 'packaging', 'одноразовая посуда': 'packaging', 'ланч-боксы': 'packaging',
}


@dataclass
class Parsed:
    category: str | None = None
    city: str | None = None
    certs: bool = False
    horeca: bool = False
    price_known: bool = False
    volume_kg: float | None = None
    volume_rub: float | None = None
    text: str = ''
    matched: list[str] = field(default_factory=list)


def parse(q: str) -> Parsed:
    s = ' ' + q.lower().replace('ё', 'е') + ' '
    p = Parsed()
    for alias, cid in ALIASES.items():
        if alias in s:
            p.category = cid
            p.matched.append(alias)
            break
    if not p.category:
        best = 0
        for c in CATEGORIES:
            hits = [w for w in c.words if w in s]
            if len(hits) > best:
                best, p.category = len(hits), c.id
                p.matched = hits
    for c in CITIES:
        hit = next((w for w in c.words if w in s), None)
        if hit:
            p.city = c.id
            p.matched.append(hit)
            break
    if re.search(r'сертифик|деклараци|документ|ветеринар|меркурий|халяль|хассп|haccp', s):
        p.certs = True
    if re.search(r'horeca|хорека|ресторан|общепит|кафе', s):
        p.horeca = True
    if re.search(r'прайс|цен[аыу]|стоимост', s):
        p.price_known = True
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(кг|килограмм|т\b|тонн)', s)
    if m:
        v = float(m.group(1).replace(',', '.'))
        p.volume_kg = v * 1000 if m.group(2).startswith('т') else v
    m = re.search(r'(\d[\d\s]*(?:[.,]\d+)?)\s*(тыс\.?|к\b)?\s*(?:₽|руб)', s)
    if m:
        v = float(re.sub(r'\s', '', m.group(1)).replace(',', '.'))
        p.volume_rub = v * 1000 if m.group(2) else v
    p.text = q.strip()
    return p
