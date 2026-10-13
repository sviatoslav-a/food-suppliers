"""Step 2. Polite crawler: fetch a supplier's home page plus the pages that usually hold
contacts, delivery terms, prices, requisites and certificates. Deterministic regexes pull
INN, phones and emails with the exact source URL."""

import asyncio
import json
import re
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

OUT = Path('data/cache/pages')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36 SupplierScout/0.1 (research)'
KEYWORDS = ('контакт', 'о компании', 'о нас', 'доставк', 'оплат', 'услови', 'прайс', 'цен', 'сертифик', 'документ',
            'реквизит', 'сотрудничеств', 'оптов', 'horeca', 'ресторан', 'каталог', 'contact', 'about', 'delivery', 'price')
MAX_PAGES = 7
PAGE_CHARS = 7000

INN_RE = re.compile(r'ИНН\s*(?:/\s*КПП)?\s*[:№]?\s*(\d{10}|\d{12})\b')
PHONE_RE = re.compile(r'(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
# Personal-looking mailboxes are skipped (152-FZ): keep role addresses only.
ROLE_MAIL = re.compile(r'^(info|sale|sales|opt|zakaz|order|office|mail|hello|horeca|client|market|manager|torg|td|contact|support|admin|zakupki|snab|shop|ekb|msk|post)', re.I)


def norm_phone(p: str) -> str:
    d = re.sub(r'\D', '', p)
    d = '7' + d[1:] if len(d) == 11 and d[0] == '8' else d
    return f'+7 ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}' if len(d) == 11 else p


def page_text(html: str) -> tuple[str, str, list[tuple[str, str]]]:
    tree = HTMLParser(html)
    title = (tree.css_first('title').text(strip=True) if tree.css_first('title') else '')[:200]
    links = [(a.attributes.get('href') or '', a.text(strip=True)) for a in tree.css('a')]
    for tag in tree.css('script, style, noscript, svg, iframe'):
        tag.decompose()
    body = tree.body.text(separator=' ', strip=True) if tree.body else ''
    return title, re.sub(r'\s+', ' ', body), links


def pick_links(base: str, links: list[tuple[str, str]]) -> list[str]:
    host = urlparse(base).netloc
    seen, out = set(), []
    for href, text in links:
        if not href or href.startswith(('mailto:', 'tel:', '#', 'javascript:')):
            continue
        url = urljoin(base, href).split('#')[0]
        if urlparse(url).netloc != host or url in seen or re.search(r'\.(pdf|jpg|png|zip|docx?|xlsx?)$', url, re.I):
            continue
        hay = f'{text} {url}'.lower()
        if any(k in hay for k in KEYWORDS):
            seen.add(url)
            out.append(url)
    # contacts and delivery first
    return sorted(out, key=lambda u: 0 if re.search(r'contact|kontakt|контакт|dostav|delivery|доставк|rekviz|реквизит', u.lower()) else 1)


def facts(pages: dict[str, dict]) -> dict:
    out = {'inn': [], 'phones': [], 'emails': []}
    for url, p in pages.items():
        t = p['text']
        for m in INN_RE.finditer(t):
            out['inn'].append({'value': m.group(1), 'source': url})
        for m in PHONE_RE.finditer(t):
            out['phones'].append({'value': norm_phone(m.group(0)), 'source': url})
        for m in EMAIL_RE.finditer(t):
            e = m.group(0).rstrip('.').lower()
            if ROLE_MAIL.match(e) and not e.endswith(('.png', '.jpg', '.webp')):
                out['emails'].append({'value': e, 'source': url})
    for k in out:  # dedupe by value, keep first source
        seen, uniq = set(), []
        for x in out[k]:
            if x['value'] not in seen:
                seen.add(x['value'])
                uniq.append(x)
        out[k] = uniq[:4]
    return out


async def crawl(client: httpx.AsyncClient, start: str) -> dict:
    root = f'{urlparse(start).scheme}://{urlparse(start).netloc}/'
    robots = urllib.robotparser.RobotFileParser()
    try:
        r = await client.get(urljoin(root, '/robots.txt'))
        robots.parse(r.text.splitlines() if r.status_code == 200 else [])
    except httpx.HTTPError:
        robots.parse([])
    pages: dict[str, dict] = {}
    fact_pages: dict[str, dict] = {}
    visited = set()
    queue = [start] if start.rstrip('/') == root.rstrip('/') else [start, root]
    while queue and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited or not robots.can_fetch(UA, url):
            continue
        visited.add(url)
        try:
            r = await client.get(url)
            await asyncio.sleep(1.0)  # politeness: 1 req/s per site
        except httpx.HTTPError as e:
            if not pages:
                return {'start': start, 'error': str(e)[:200], 'pages': {}}
            continue
        if r.status_code != 200 or 'html' not in r.headers.get('content-type', ''):
            continue
        title, text, links = page_text(r.text)
        contact_links = ' '.join(h.removeprefix('mailto:').removeprefix('tel:').split('?')[0]
                                 for h, _ in links if h.startswith(('mailto:', 'tel:')))
        fact_pages[str(r.url)] = {'text': text + ' ' + contact_links}
        pages[str(r.url)] = {'title': title, 'text': text[:PAGE_CHARS]}
        if len(pages) == 1:
            queue += [u for u in pick_links(str(r.url), links) if u not in queue]
    return {'start': start, 'pages': pages, 'facts': facts(fact_pages)}


def cache_path(url: str) -> Path:
    return OUT / (re.sub(r'[^\w.-]', '_', urlparse(url).netloc.removeprefix('www.')) + '.json')


async def fetch_all(urls: list[str], concurrency: int = 8) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers={'User-Agent': UA, 'Accept-Language': 'ru'}, timeout=20, follow_redirects=True) as client:
        async def one(u: str):
            p = cache_path(u)
            if p.exists():
                return
            async with sem:
                res = await crawl(client, u)
            p.write_text(json.dumps(res, ensure_ascii=False))
            print(f'{len(res.get("pages", {}))} pages  {u}', flush=True)
        await asyncio.gather(*(one(u) for u in urls))


def main() -> None:
    from pipeline.discover import OUT as DISC, domain
    seen, urls = set(), []
    for f in sorted(DISC.glob('*.json')):
        for it in json.loads(f.read_text()):
            d = domain(it['url'])
            if d not in seen:
                seen.add(d)
                urls.append(it['url'])
    print(f'{len(urls)} unique sites')
    asyncio.run(fetch_all(urls))


if __name__ == '__main__':
    main()
