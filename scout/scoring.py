"""Explainable supplier score (0-100) for a given request.

Each component returns points, its maximum and a human reason, so the UI can show
*why* a supplier ranks where it does. Weights reflect what a restaurant buyer checks
first: can they supply this, here, reliably, legally, and on what terms."""

from dataclasses import dataclass
from datetime import date

from scout.taxonomy import BY_ID, CITY_BY_ID


@dataclass
class Request:
    category: str | None = None
    city: str | None = None
    volume_kg: float | None = None  # expected order size
    volume_rub: float | None = None
    certs: bool = False


@dataclass
class Part:
    key: str
    label: str
    points: float
    max: float
    why: str


def years_since(d: str | None, today: date | None = None) -> float | None:
    if not d:
        return None
    try:
        dd, mm, yy = (int(x) for x in d.split('.'))
        today = today or date.today()
        return (today - date(yy, mm, dd)).days / 365.25
    except ValueError:
        return None


def serves_city(s: dict, city_id: str | None) -> tuple[str, str]:
    """'local' | 'delivers' | 'region' | 'other' and a reason."""
    if not city_id:
        return 'local', ''
    c = CITY_BY_ID[city_id]
    home = (s.get('home_city') or s.get('city') or '').lower()
    if any(w in home for w in c.words):
        return 'local', f'офис или склад: {s.get("home_city") or s.get("city")}'
    area = s.get('service_area') or {}
    hay = ' '.join([area.get('text') or '', *area.get('cities', [])]).lower()
    if any(w in hay for w in c.words):
        return 'delivers', f'доставляют в {c.name}'
    if s.get('region_code') in ({'66'} if city_id == 'ekb' else {'77', '50'}):
        return 'region', f'зарегистрированы в регионе: {c.region}'
    if any(k in hay for k in ('вся россия', 'всей россии', 'по россии', 'все регионы россии', 'в любые регионы россии')):
        return 'delivers', 'доставка по России'
    return 'other', 'другой регион, доставку нужно уточнить'


def score(s: dict, r: Request, today: date | None = None) -> tuple[int, list[Part]]:
    parts: list[Part] = []

    # 1. Category fit (25)
    if r.category:
        cat = BY_ID[r.category]
        if r.category in s['categories']:
            parts.append(Part('category', 'Ассортимент', 25, 25, f'есть категория "{cat.name}"'))
        elif any(w in ' '.join(s['products']).lower() for w in cat.words):
            parts.append(Part('category', 'Ассортимент', 15, 25, 'категория найдена в списке товаров'))
        else:
            parts.append(Part('category', 'Ассортимент', 0, 25, 'категория не подтверждена'))
    else:
        parts.append(Part('category', 'Ассортимент', 20, 25, 'категория не задана'))

    # 2. Geography (20)
    where, why = serves_city(s, r.city)
    pts = {'local': 20, 'delivers': 15, 'region': 12, 'other': 3}[where]
    parts.append(Part('geo', 'География', pts, 20, why or 'город не задан'))

    # 3. Reliability (20): registry, age, size
    rel, notes = 0.0, []
    if s['verified_egrul'] and s.get('status') == 'active':
        rel += 8
        notes.append('действующая компания по ЕГРЮЛ')
    elif s['verified_registry']:
        rel += 6
        notes.append('есть в реестре МСП ФНС')
    else:
        notes.append('ИНН не подтверждён')
    age = years_since(s.get('reg_date'), today)
    if age is not None:
        rel += min(8, age * 8 / 5)
        notes.append(f'на рынке {age:.0f} лет' if age >= 1 else 'компания моложе года')
    if s.get('sme') in ('small', 'medium'):
        rel += 4
        notes.append({'small': 'малое предприятие', 'medium': 'среднее предприятие'}[s['sme']])
    elif s.get('sme') == 'micro':
        rel += 2
        notes.append('микропредприятие')
    parts.append(Part('reliability', 'Надёжность', round(min(20, rel), 1), 20, ', '.join(notes)))

    # 4. Documents (10)
    if s['certificates']:
        parts.append(Part('docs', 'Документы', 10, 10, f'на сайте: {s["certificates"][0]["text"][:70]}'))
    else:
        parts.append(Part('docs', 'Документы', 0, 10, 'про сертификаты на сайте ничего нет'))

    # 5. Commercial transparency (15)
    t, have, miss = 0, [], []
    for key, pts_, label in (('prices', 6, 'цены'), ('moq', 5, 'мин. заказ'), ('delivery', 4, 'доставка')):
        if s.get(key):
            t += pts_
            have.append(label)
        else:
            miss.append(label)
    why = ('известно: ' + ', '.join(have) if have else 'условия не опубликованы') + ('; уточнить: ' + ', '.join(miss) if have and miss else '')
    parts.append(Part('terms', 'Условия', t, 15, why))

    # 6. HoReCa focus (10)
    if s['horeca']:
        parts.append(Part('horeca', 'Работа с HoReCa', 10, 10, 'прямо пишут про рестораны и общепит'))
    elif s['b2b']:
        parts.append(Part('horeca', 'Работа с HoReCa', 6, 10, 'оптовые продажи бизнесу'))
    else:
        parts.append(Part('horeca', 'Работа с HoReCa', 0, 10, 'нет признаков работы с бизнесом'))

    total = sum(p.points for p in parts)

    # Penalties: MOQ above the buyer's volume, red flags.
    moq = s.get('moq') or {}
    if r.volume_kg and moq.get('kg') and moq['kg'] > r.volume_kg:
        total -= 15
        parts.append(Part('moq', 'Мин. заказ', -15, 0, f'минимум {moq["kg"]:g} кг больше вашего объёма {r.volume_kg:g} кг'))
    if r.volume_rub and moq.get('rub') and moq['rub'] > r.volume_rub:
        total -= 15
        parts.append(Part('moq', 'Мин. заказ', -15, 0, f'минимум {moq["rub"]:,.0f} ₽ больше вашего объёма'.replace(',', ' ')))
    if s['red_flags']:
        total -= 5 * min(2, len(s['red_flags']))
        parts.append(Part('flags', 'Риски', -5 * min(2, len(s['red_flags'])), 0, '; '.join(s['red_flags'][:2])))
    return max(0, min(100, round(total))), parts


def next_action(s: dict) -> str:
    """What the buyer should do next with this supplier."""
    missing = [label for key, label in (('prices', 'прайс'), ('moq', 'минимальный заказ'), ('delivery', 'условия доставки')) if not s.get(key)]
    channel = (f'написать на {s["emails"][0]["value"]}' if s['emails']
               else f'позвонить {s["phones"][0]["value"]}' if s['phones'] else 'оставить заявку на сайте')
    if missing:
        return f'{channel.capitalize()}: запросить {", ".join(missing)}'
    if not s['certificates']:
        return f'{channel.capitalize()}: запросить декларации и сертификаты'
    return f'{channel.capitalize()}: запросить пробную поставку'
