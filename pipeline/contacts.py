"""Refresh contact evidence for eligible suppliers with no phone/email.

No LLM calls: recrawl public pages and keep deterministic facts with source URLs.
Run before pipeline.build. Existing facts and extracted commercial terms are retained.
"""
import asyncio
import json

import httpx

from pipeline.build import eligible
from pipeline.extract import OUT
from pipeline.fetch import UA, cache_path, crawl


async def main():
    async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=20, follow_redirects=True) as client:
        for path in sorted(OUT.glob('*.json')):
            record = json.loads(path.read_text())
            old = record.get('_facts') or {}
            if not eligible(record) or old.get('phones') or old.get('emails'):
                continue
            fresh = await crawl(client, record['_start'])
            if not fresh.get('pages'):
                print(record['_start'], 'unavailable; retained old evidence')
                continue
            cache_path(record['_start']).write_text(json.dumps(fresh, ensure_ascii=False))
            for key in ('phones', 'emails'):  # do not change legal identity on a contact-only refresh
                if fresh['facts'].get(key):
                    old[key] = fresh['facts'][key]
            record['_facts'] = old
            record['_pages'] = list(dict.fromkeys(record.get('_pages', []) + list(fresh['pages'])))
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
            print(record['_start'], len(old.get('phones', [])), 'phones,', len(old.get('emails', [])), 'emails')


if __name__ == '__main__':
    asyncio.run(main())
