"""Search, supplier details and comparison. The single place the web app, JSON API
and MCP server go through, so all three rank suppliers the same way."""

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from functools import cached_property

from scout import db as dbm
from scout.query import parse
from scout.scoring import Request, next_action, score, serves_city
from scout.taxonomy import BY_ID, CATEGORIES, CITY_BY_ID

SORTS = ('score', 'age', 'complete', 'name')


@dataclass
class Params:
    q: str = ''
    category: str | None = None
    city: str | None = None
    volume_kg: float | None = None
    volume_rub: float | None = None
    certs: bool = False
    horeca: bool = False
    price: bool = False
    verified: bool = False
    local: bool = False
    sort: str = 'score'
    parsed: list[str] = field(default_factory=list)

    def request(self) -> Request:
        return Request(self.category, self.city, self.volume_kg, self.volume_rub, self.certs)


def completeness(s: dict) -> int:
    keys = ('prices', 'moq', 'delivery', 'certificates', 'emails', 'phones', 'service_area', 'inn')
    return round(100 * sum(bool(s.get(k)) for k in keys) / len(keys))


class Store:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or dbm.connect()

    @cached_property
    def all(self) -> list[dict]:
        rows = [dbm.row_to_dict(r) for r in self.conn.execute('SELECT * FROM suppliers')]
        for s in rows:
            s['completeness'] = completeness(s)
        return rows

    @cached_property
    def by_id(self) -> dict[str, dict]:
        return {s['id']: s for s in self.all}

    @cached_property
    def meta(self) -> dict:
        return dict(self.conn.execute('SELECT key, value FROM meta').fetchall())

    def registry_count(self, category: str | None, city: str | None) -> dict | None:
        if not category or not city:
            return None
        region = CITY_BY_ID[city].region_code
        r = self.conn.execute('SELECT total, legal FROM registry_counts WHERE category=? AND region=?', (category, region)).fetchone()
        return {'total': r[0], 'legal': r[1], 'region': CITY_BY_ID[city].region} if r else None

    def text_hits(self, q: str) -> dict[str, float]:
        words = [w for w in re.findall(r'\w{3,}', q.lower()) if not w.isdigit()]
        if not words:
            return {}
        match = ' OR '.join(f'"{w[:max(4, len(w) - 2)]}"*' for w in words)
        try:
            return {r[0]: -r[1] for r in self.conn.execute(
                'SELECT id, bm25(suppliers_fts) FROM suppliers_fts WHERE suppliers_fts MATCH ?', (match,))}
        except sqlite3.OperationalError:
            return {}

    def resolve(self, p: Params) -> Params:
        """Fill structured filters from the free-text query when the form left them empty."""
        if p.q:
            x = parse(p.q)
            p.category = p.category or x.category
            p.city = p.city or x.city
            p.certs = p.certs or x.certs
            p.horeca = p.horeca or x.horeca
            p.price = p.price or x.price_known
            p.volume_kg = p.volume_kg or x.volume_kg
            p.volume_rub = p.volume_rub or x.volume_rub
            p.parsed = x.matched
        if p.category not in BY_ID:
            p.category = None
        if p.city not in CITY_BY_ID:
            p.city = None
        if p.sort not in SORTS:
            p.sort = 'score'
        return p

    def rate(self, s: dict, p: Params) -> dict:
        total, parts = score(s, p.request())
        where, why = serves_city(s, p.city)
        return {**s, 'score': total, 'parts': [asdict(x) for x in parts], 'where': where, 'where_why': why,
                'next_action': next_action(s)}

    def search(self, p: Params) -> dict:
        p = self.resolve(p)
        hits = self.text_hits(p.q) if p.q else {}
        out = []
        for s in self.all:
            if p.category:
                cat = BY_ID[p.category]
                if p.category not in s['categories'] and not any(w in ' '.join(s['products']).lower() for w in cat.words):
                    continue
            if p.certs and not s['certificates']:
                continue
            if p.horeca and not s['horeca']:
                continue
            if p.price and not s['prices']:
                continue
            if p.verified and not s['verified_egrul']:
                continue
            r = self.rate(s, p)
            if p.local and r['where'] == 'other':
                continue
            r['text_hit'] = hits.get(s['id'], 0)
            out.append(r)
        # With a free-text query and no category, keep only text matches.
        if p.q and not p.category and not p.parsed:
            out = [r for r in out if r['text_hit']]
        key = {
            'score': lambda r: (-r['score'], -r['text_hit'], r['name']),
            'age': lambda r: (r['reg_date'] is None, _date_key(r['reg_date']), r['name']),
            'complete': lambda r: (-r['completeness'], -r['score']),
            'name': lambda r: r['name'].lower(),
        }[p.sort]
        out.sort(key=key)
        facets = {c.id: 0 for c in CATEGORIES}
        for s in self.all:
            for c in s['categories']:
                if c in facets:
                    facets[c] += 1
        return {'params': asdict(p), 'results': out, 'total': len(out), 'facets': facets,
                'registry': self.registry_count(p.category, p.city)}

    def get(self, sid: str, p: Params | None = None) -> dict | None:
        s = self.by_id.get(sid)
        return self.rate(s, self.resolve(p or Params())) if s else None

    def compare(self, ids: list[str], p: Params | None = None) -> list[dict]:
        p = self.resolve(p or Params())
        return [self.rate(self.by_id[i], p) for i in dict.fromkeys(ids) if i in self.by_id]


def _date_key(d: str | None) -> tuple:
    if not d:
        return (9999,)
    dd, mm, yy = d.split('.')
    return (int(yy), int(mm), int(dd))
