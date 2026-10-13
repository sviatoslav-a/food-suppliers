"""Step 1. An LLM agent with web search finds supplier websites per (category, city)."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from pipeline.llm import parse_json, run
from scout.taxonomy import CATEGORIES, CITIES

OUT = Path('data/cache/discover')
SKIP_DOMAINS = ('2gis', 'avito', 'pulscen', 'yell', 'yandex', 'google', 'ozon', 'wildberries', 'tiu.ru', 'zoon',
                'flamp', 'rusprofile', 'checko', 'list-org', 'agroserver', 'productcenter', 'satu', 'vk.com',
                'hh.ru', 'b2b-center', 'supl.biz', 'spark-interfax', 'sbis', 'tenchat', 'youtube', 'market.yandex')

PROMPT = """You are a procurement research agent for a restaurant chain.
Use WebSearch (several queries, in Russian) to find wholesale suppliers in this niche:
  category: {category}
  city/region: {city} ({region})
Search phrases to try: "{query} {city}", "{category} оптом {city}", "{category} HoReCa {city} доставка".
Rules:
- Only companies that sell B2B / wholesale (оптом, HoReCa, для ресторанов, для общепита).
- Return the company's OWN website, not aggregators, marketplaces or directories
  (2gis, avito, pulscen, yell, rusprofile, agroserver, etc.).
- Prefer companies located in or delivering to {city}. Federal suppliers with a branch there are fine.
- Up to {n} companies, no duplicates.
Reply with ONLY a JSON array: [{{"name": "...", "url": "https://...", "why": "one short line from the search result"}}]"""


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix('www.')


ROUND2 = """
This is a second pass. Do NOT return these already-known companies: {known}.
Use different queries, e.g. "{category} оптом {city} прайс", "{category} поставки в рестораны {city}", "дистрибьютор {category} {city}"."""


def discover(cat, city, n: int = 12, round_: int = 1) -> list[dict]:
    path = OUT / (f'{cat.id}_{city.id}.json' if round_ == 1 else f'{cat.id}_{city.id}_r{round_}.json')
    if path.exists():
        return json.loads(path.read_text())
    prompt = PROMPT.format(category=cat.name, city=city.name, region=city.region, query=cat.query, n=n)
    if round_ > 1:
        known = [i['name'] for f in OUT.glob(f'{cat.id}_{city.id}*.json') for i in json.loads(f.read_text())]
        prompt += ROUND2.format(known=', '.join(known) or 'none', category=cat.name, city=city.name)
    text = run(prompt,
               model='haiku', tools='WebSearch', timeout=400)
    items = [i for i in parse_json(text) if isinstance(i, dict) and i.get('url', '').startswith('http')]
    items = [i | {'category': cat.id, 'city': city.id} for i in items if not any(s in domain(i['url']) for s in SKIP_DOMAINS)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cats', default=','.join(c.id for c in CATEGORIES))
    ap.add_argument('--cities', default=','.join(c.id for c in CITIES))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--round', type=int, default=1)
    ap.add_argument('--below', type=int, default=0, help='round>1: only pairs with fewer candidates')
    a = ap.parse_args()
    jobs = [(c, t) for c in CATEGORIES if c.id in a.cats.split(',') for t in CITIES if t.id in a.cities.split(',')]
    if a.round > 1:
        count = lambda c, t: sum(len(json.loads(f.read_text())) for f in OUT.glob(f'{c.id}_{t.id}*.json'))
        jobs = [(c, t) for c, t in jobs if count(c, t) < a.below]
        print('round', a.round, [f'{c.id}/{t.id}' for c, t in jobs])

    def go(job):
        try:
            r = discover(*job, round_=a.round)
            print(f'{job[0].id}/{job[1].id}: {len(r)}', flush=True)
        except Exception as e:  # keep going; a failed pair can be re-run
            print(f'{job[0].id}/{job[1].id}: ERROR {e}', flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(go, jobs))


if __name__ == '__main__':
    main()
