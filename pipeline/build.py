"""Step 5. Assemble data/suppliers.sqlite from extracted records + registry verification."""

import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pipeline.discover import OUT as DISC, domain
from pipeline.extract import OUT as EXTRACT
from pipeline.verify import egrul_lookup, registry_lookup
from scout.db import DB_PATH, SCHEMA
from scout.taxonomy import BY_ID, CATEGORIES, REGION_GROUP, categories_for_okved

REGISTRY = Path('data/registry.sqlite')
REGION_NAMES = {'66': 'Свердловская область', '77': 'Москва', '50': 'Московская область'}
BAD_KINDS = {'retail', 'marketplace', 'not_food'}


def slug(url: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', domain(url).lower()).strip('-')


def discovered_categories() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in DISC.glob('*.json'):
        for it in json.loads(f.read_text()):
            out.setdefault(domain(it['url']), set()).add(it['category'])
    return out


def clean_list(xs, need=('source',)) -> list:
    return [x for x in (xs or []) if isinstance(x, dict) and all(x.get(k) for k in need)]


def eligible(e: dict) -> bool:
    # Packaging was classified as "not_food" by the original food-only prompt.
    food_packaging = ('packaging' in (e.get('categories') or []) and
                      (e.get('horeca') or any(w in (e.get('description') or '').lower()
                       for w in ('пищев', 'одноразов', 'фастфуд', 'ресторан'))))
    return bool(e.get('b2b') or e.get('horeca')) and (
        e.get('kind') not in BAD_KINDS or (e.get('kind') == 'not_food' and food_packaging))


def build() -> None:
    reg = sqlite3.connect(REGISTRY)
    disc = discovered_categories()
    rows, seen_inn, skipped = [], set(), []
    client = httpx.Client(timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
    for f in sorted(EXTRACT.glob('*.json')):
        e = json.loads(f.read_text())
        site = e['_start']
        if not eligible(e):
            skipped.append((domain(site), e.get('kind'), 'not a B2B food supplier'))
            continue
        facts = e.get('_facts') or {}
        inn = next((x['value'] for x in facts.get('inn', [])), None)
        r = registry_lookup(reg, inn) if inn else None
        eg = None
        if inn:
            try:
                eg = egrul_lookup(inn, client)
            except Exception as ex:  # network hiccup: keep the supplier, mark unverified
                print('egrul', inn, ex)
        if inn and inn in seen_inn:
            skipped.append((domain(site), e.get('kind'), f'duplicate INN {inn}'))
            continue
        if inn:
            seen_inn.add(inn)
        cats = [c for c in (e.get('categories') or []) if c in BY_ID]
        found_for = disc.get(domain(site), set())
        okved_cats = categories_for_okved([r['okved_main']]) if r else []
        if not cats:
            cats = sorted(found_for | set(okved_cats))
        if not cats:
            skipped.append((domain(site), e.get('kind'), 'no category'))
            continue
        region_code = (r or {}).get('region') or ''
        if not region_code and eg and eg.get('rn'):
            region_code = next((k for k, v in REGION_NAMES.items() if v.lower() in eg['rn'].lower()), '')
        status = 'liquidated' if eg and eg.get('e') else 'active' if eg else ''
        rows.append({
            'id': slug(site),
            'name': (e.get('name') or domain(site))[:80],
            'legal_name': (eg or {}).get('c') or e.get('legal_name') or (r or {}).get('short_name'),
            'inn': inn, 'ogrn': (eg or {}).get('o') or (r or {}).get('ogrn'),
            'kind': e.get('kind'), 'sme': (r or {}).get('sme'),
            'reg_date': (eg or {}).get('r'), 'status': status,
            'region_code': region_code, 'region': (eg or {}).get('rn') or REGION_NAMES.get(region_code, ''),
            'city': e.get('city') or (r or {}).get('city'), 'home_city': e.get('city') or (r or {}).get('city'),
            'website': f'{urlparse(site).scheme}://{urlparse(site).netloc}',
            'description': e.get('description') or '',
            'okved_main': (r or {}).get('okved_main'), 'okved_name': (r or {}).get('okved_main_name'),
            'horeca': int(bool(e.get('horeca'))), 'b2b': int(bool(e.get('b2b'))),
            'categories': cats, 'products': [p for p in (e.get('products') or []) if isinstance(p, str)][:10],
            'moq': e.get('moq') if (e.get('moq') or {}).get('source') else None,
            'prices': clean_list(e.get('prices'), ('product', 'price', 'source'))[:5],
            'delivery': e.get('delivery') if (e.get('delivery') or {}).get('source') else None,
            'service_area': e.get('service_area') if (e.get('service_area') or {}).get('source') else None,
            'certificates': clean_list(e.get('certificates'), ('text', 'source'))[:4],
            'payment': e.get('payment'),
            'phones': facts.get('phones', [])[:3], 'emails': facts.get('emails', [])[:3],
            'red_flags': [x for x in (e.get('red_flags') or []) if isinstance(x, str)][:3],
            'pages': e.get('_pages', []),
            'verified_registry': int(r is not None), 'verified_egrul': int(bool(eg)),
            'extracted_at': date.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    client.close()

    if not rows:
        raise RuntimeError('No eligible suppliers; existing database was not changed')
    temporary = DB_PATH.with_suffix('.building.sqlite')
    temporary.unlink(missing_ok=True)
    db = sqlite3.connect(temporary)
    db.executescript(SCHEMA)
    cols = list(rows[0])
    for row in rows:
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in row.values()]
        db.execute(f'INSERT INTO suppliers ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})', vals)
        db.execute('INSERT INTO suppliers_fts (id, name, description, products) VALUES (?,?,?,?)',
                   (row['id'], row['name'], row['description'], ' '.join(row['products'])))
    for c in CATEGORIES:
        for key, regions in REGION_GROUP.items():
            where = ' OR '.join(['okved_main LIKE ?'] * len(c.okved))
            q = f'SELECT count(*), sum(kind = "ul") FROM registry WHERE region IN ({",".join("?" * len(regions))}) AND ({where})'
            total, legal = reg.execute(q, [*regions, *[p + '%' for p in c.okved]]).fetchone()
            db.execute('INSERT INTO registry_counts VALUES (?,?,?,?)', (c.id, key, total, legal or 0))
    as_of = reg.execute('SELECT max(as_of) FROM registry').fetchone()[0]
    for k, v in {'built_at': date.today().isoformat(), 'registry_as_of': as_of, 'suppliers': len(rows),
                 'skipped': len(skipped), 'sites_checked': len(list(EXTRACT.glob('*.json')))}.items():
        db.execute('INSERT INTO meta VALUES (?,?)', (k, str(v)))
    db.commit()
    db.close()
    reg.close()
    temporary.replace(DB_PATH)
    Path('data/build_report.json').write_text(json.dumps({'kept': len(rows), 'skipped': skipped}, ensure_ascii=False, indent=1))
    print(f'{len(rows)} suppliers, {len(skipped)} skipped -> {DB_PATH}')


if __name__ == '__main__':
    build()
