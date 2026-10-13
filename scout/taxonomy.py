"""Product categories, their OKVED codes and search vocabulary, and supported cities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    okved: tuple[str, ...]  # prefixes, matched against main and additional OKVED codes
    words: tuple[str, ...]  # stems used by the query parser and keyword search
    query: str  # web search phrase used by the discovery agent


CATEGORIES: tuple[Category, ...] = (
    Category('meat', 'Мясо и птица', ('46.32', '10.11', '10.12', '10.13'),
             ('мяс', 'говяд', 'свин', 'птиц', 'куриц', 'курин', 'индейк', 'фарш', 'бекон', 'meat', 'chicken', 'beef'),
             'поставщик мяса и птицы оптом для ресторанов'),
    Category('fish', 'Рыба и морепродукты', ('46.38.1', '10.20'),
             ('рыб', 'лосос', 'семг', 'форел', 'тунец', 'креветк', 'морепрод', 'икр', 'fish', 'salmon', 'seafood'),
             'поставщик рыбы и морепродуктов оптом для HoReCa'),
    Category('dairy', 'Молочная продукция и сыры', ('46.33', '10.51', '10.52'),
             ('молок', 'молоч', 'сыр', 'сливк', 'творог', 'сметан', 'масло сливоч', 'моцарел', 'dairy', 'cheese', 'milk'),
             'поставщик молочной продукции и сыров оптом для ресторанов'),
    Category('veg', 'Овощи, фрукты, зелень', ('46.31', '01.13', '01.2'),
             ('овощ', 'фрукт', 'зелен', 'салат', 'авокадо', 'томат', 'огурц', 'картоф', 'ягод', 'vegetable', 'fruit'),
             'поставщик овощей и фруктов для ресторанов'),
    Category('grocery', 'Бакалея и заморозка', ('46.36', '46.37', '46.38.2', '46.39', '10.61', '10.85'),
             ('бакале', 'круп', 'мук', 'сахар', 'макарон', 'специ', 'соус', 'масло растит', 'заморо', 'полуфабрикат', 'grocery'),
             'поставщик бакалеи и замороженной продукции для общепита'),
    Category('asian', 'Продукты для японской и азиатской кухни', ('46.38.2', '46.39'),
             ('нори', 'рис для суши', 'суши', 'васаби', 'имбир', 'соев', 'унаги', 'тобико', 'японск', 'азиатск', 'sushi', 'nori'),
             'поставщик продуктов для суши и японской кухни оптом'),
    Category('drinks', 'Напитки', ('46.34', '11.07', '46.37'),
             ('напит', 'вода', 'сок', 'лимонад', 'кофе', 'чай', 'сироп', 'drinks', 'coffee', 'water'),
             'поставщик напитков, кофе и чая для HoReCa'),
    Category('packaging', 'Упаковка и одноразовая посуда', ('46.76', '46.49', '17.21', '22.22', '46.69'),
             ('упаков', 'контейнер', 'коробк', 'пакет', 'одноразов', 'ланч-бокс', 'стакан', 'крафт', 'packaging', 'box'),
             'поставщик упаковки для доставки еды и одноразовой посуды'),
)
BY_ID = {c.id: c for c in CATEGORIES}


@dataclass(frozen=True)
class City:
    id: str
    name: str
    region_code: str  # FNS region code
    region: str
    words: tuple[str, ...]


CITIES: tuple[City, ...] = (
    City('ekb', 'Екатеринбург', '66', 'Свердловская область', ('екатеринбург', 'екб', 'ебург', 'свердловск', 'урал', 'ekaterinburg', 'yekaterinburg')),
    City('msk', 'Москва', '77', 'Москва и область', ('москв', 'мск', 'подмосков', 'moscow')),
)
CITY_BY_ID = {c.id: c for c in CITIES}
# Moscow region (50) is served together with Moscow (77).
REGION_GROUP = {'66': ('66',), '77': ('77', '50')}

ALL_OKVED_PREFIXES = tuple(sorted({p for c in CATEGORIES for p in c.okved}))


def categories_for_okved(codes: list[str]) -> list[str]:
    """Category ids whose OKVED prefixes match any of the codes."""
    return [c.id for c in CATEGORIES if any(code.startswith(p) for code in codes for p in c.okved)]
