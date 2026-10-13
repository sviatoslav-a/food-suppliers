"""SQLite storage. The app database is read-only at runtime and rebuilt by the pipeline."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'suppliers.sqlite'

SCHEMA = """
CREATE TABLE suppliers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL, legal_name TEXT, inn TEXT, ogrn TEXT, kind TEXT, sme TEXT,
  reg_date TEXT, status TEXT, region_code TEXT, region TEXT, city TEXT, home_city TEXT,
  website TEXT, description TEXT, okved_main TEXT, okved_name TEXT,
  horeca INTEGER, b2b INTEGER,
  categories TEXT, products TEXT, moq TEXT, prices TEXT, delivery TEXT, service_area TEXT,
  certificates TEXT, payment TEXT, phones TEXT, emails TEXT, red_flags TEXT, pages TEXT,
  verified_registry INTEGER, verified_egrul INTEGER, extracted_at TEXT
);
CREATE VIRTUAL TABLE suppliers_fts USING fts5(id UNINDEXED, name, description, products, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE registry_counts (category TEXT, region TEXT, total INTEGER, legal INTEGER, PRIMARY KEY (category, region));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_FIELDS = ('categories', 'products', 'moq', 'prices', 'delivery', 'service_area', 'certificates', 'phones',
               'emails', 'red_flags', 'pages')


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in JSON_FIELDS:
        d[f] = json.loads(d[f]) if d.get(f) else ([] if f in ('categories', 'products', 'prices', 'certificates', 'phones', 'emails', 'red_flags', 'pages') else None)
    d['horeca'], d['b2b'] = bool(d['horeca']), bool(d['b2b'])
    d['verified_registry'], d['verified_egrul'] = bool(d['verified_registry']), bool(d['verified_egrul'])
    return d
