"""Stream the FNS SME register (Реестр МСП) zip into a local SQLite registry.

Keeps food-related companies: main OKVED in our categories anywhere in Russia, or any
OKVED match in the regions we serve. Source: https://www.nalog.gov.ru/opendata/7707329152-rsmp/
"""

import argparse
import sqlite3
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from lxml import etree

from scout.taxonomy import ALL_OKVED_PREFIXES, REGION_GROUP

SERVED_REGIONS = {r for group in REGION_GROUP.values() for r in group}
SME = {'1': 'micro', '2': 'small', '3': 'medium'}


def matches(code: str) -> bool:
    return code.startswith(ALL_OKVED_PREFIXES)


def parse_doc(doc) -> dict | None:
    okv = doc.find('СвОКВЭД')
    if okv is None:
        return None
    main_el = okv.find('СвОКВЭДОсн')
    main = main_el.get('КодОКВЭД') if main_el is not None else ''
    extra = [e.get('КодОКВЭД') for e in okv.findall('СвОКВЭДДоп')]
    mn = doc.find('СведМН')
    region = mn.get('КодРегион') if mn is not None else ''
    if not (matches(main) or (region in SERVED_REGIONS and any(matches(c) for c in extra))):
        return None
    city = ''
    if mn is not None:
        for tag in ('Город', 'НаселПункт'):
            el = mn.find(tag)
            if el is not None:
                city = el.get('Наим', '')
                break
        if not city and region in ('77', '78', '92'):
            city = mn.find('Регион').get('Наим', '') if mn.find('Регион') is not None else ''
    org = doc.find('ОргВклМСП')
    if org is not None:
        kind, inn, ogrn = 'ul', org.get('ИННЮЛ'), org.get('ОГРН')
        name, short = org.get('НаимОрг', ''), org.get('НаимОргСокр', '') or org.get('НаимОрг', '')
    else:
        ip = doc.find('ИПВклМСП')
        if ip is None:
            return None
        fio = ip.find('ФИОИП')
        kind, inn, ogrn = 'ip', ip.get('ИННФЛ'), ip.get('ОГРНИП')
        full = ' '.join(x for x in (fio.get('Фамилия'), fio.get('Имя'), fio.get('Отчество')) if x) if fio is not None else ''
        name, short = f'ИП {full}', f'ИП {full}'
    return {
        'inn': inn, 'ogrn': ogrn, 'kind': kind, 'name': name, 'short_name': short,
        'sme': SME.get(doc.get('КатСубМСП'), ''), 'region': region, 'city': city,
        'okved_main': main, 'okved_main_name': main_el.get('НаимОКВЭД', '') if main_el is not None else '',
        'okved_extra': ','.join(c for c in extra if c), 'included': doc.get('ДатаВклМСП', ''),
        'as_of': doc.get('ДатаСост', ''),
    }


def parse_file(args: tuple[str, str]) -> list[dict]:
    zpath, name = args
    with zipfile.ZipFile(zpath) as z, z.open(name) as f:
        root = etree.parse(f).getroot()
    return [r for r in (parse_doc(d) for d in root.iter('Документ')) if r]


SCHEMA = """
CREATE TABLE IF NOT EXISTS registry (
  inn TEXT PRIMARY KEY, ogrn TEXT, kind TEXT, name TEXT, short_name TEXT, sme TEXT,
  region TEXT, city TEXT, okved_main TEXT, okved_main_name TEXT, okved_extra TEXT,
  included TEXT, as_of TEXT
);
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default='data/raw/rsmp.zip')
    ap.add_argument('--out', default='data/registry.sqlite')
    ap.add_argument('--limit', type=int, default=0, help='parse only N files (for tests)')
    a = ap.parse_args()
    names = [n for n in zipfile.ZipFile(a.zip).namelist() if n.endswith('.xml')]
    if a.limit:
        names = names[: a.limit]
    Path(a.out).unlink(missing_ok=True)
    db = sqlite3.connect(a.out)
    db.executescript(SCHEMA)
    t0, n = time.time(), 0
    cols = 'inn,ogrn,kind,name,short_name,sme,region,city,okved_main,okved_main_name,okved_extra,included,as_of'
    with ProcessPoolExecutor() as ex:
        for i, rows in enumerate(ex.map(parse_file, [(a.zip, x) for x in names], chunksize=8)):
            db.executemany(f'INSERT OR REPLACE INTO registry ({cols}) VALUES ({",".join("?" * 13)})',
                           [tuple(r[c] for c in cols.split(',')) for r in rows])
            n += len(rows)
            if i % 500 == 0:
                db.commit()
                print(f'{i}/{len(names)} files, {n} rows, {time.time() - t0:.0f}s', flush=True)
    db.execute('CREATE INDEX IF NOT EXISTS reg_region ON registry(region)')
    db.commit()
    print(f'done: {n} rows in {time.time() - t0:.0f}s -> {a.out}')


if __name__ == '__main__':
    main()
