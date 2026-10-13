"""Step 4. Verify a supplier's INN against official sources:
the FNS SME register (local copy) and the EGRUL search (egrul.nalog.ru, live, rate-limited)."""

import json
import sqlite3
import time
from pathlib import Path

import httpx

CACHE = Path('data/cache/egrul')


def registry_lookup(db: sqlite3.Connection, inn: str) -> dict | None:
    db.row_factory = sqlite3.Row
    r = db.execute('SELECT * FROM registry WHERE inn = ?', (inn,)).fetchone()
    return dict(r) if r else None


def egrul_lookup(inn: str, client: httpx.Client) -> dict | None:
    """Returns the EGRUL search row: n=name, c=short name, o=OGRN, r=reg date, e=liquidation date, a=address."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'{inn}.json'
    if path.exists():
        return json.loads(path.read_text()) or None
    t = client.post('https://egrul.nalog.ru/', data={'query': inn, 'region': '', 'page': ''}).json()
    if t.get('captchaRequired'):
        raise RuntimeError('EGRUL asks for a captcha; slow down and retry later')
    rows: list = []
    for _ in range(10):
        time.sleep(0.8)
        res = client.get(f'https://egrul.nalog.ru/search-result/{t["t"]}').json()
        if res.get('status') != 'wait':
            rows = res.get('rows', [])
            break
    row = next((r for r in rows if r.get('i') == inn), None)
    path.write_text(json.dumps(row or {}, ensure_ascii=False))
    time.sleep(1.5)  # be gentle with the public service
    return row
