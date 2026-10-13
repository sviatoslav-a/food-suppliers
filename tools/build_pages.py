#!/usr/bin/env python3
"""Export the public snapshot and Jinja pages for a plain static web server.

uv run python tools/build_pages.py --base-path /food-suppliers/ --output dist
FastAPI keeps using scout/static/config.js (mode=backend); this build writes mode=static.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from lxml import html

from scout.query import ALIASES
from scout.taxonomy import CATEGORIES, CITIES
from scout.web import app, store, tpl

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path, base_path: str):
    if not base_path.startswith('/') or not base_path.endswith('/') or '..' in base_path or '?' in base_path or '#' in base_path:
        raise ValueError('base-path must be an absolute URL path ending in /')
    # Refuse to overwrite an existing directory or accidentally export source files.
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / 'scout/static', output / 'static')
    (output / '.nojekyll').touch()
    (output / 'static/config.js').write_text(
        'export const config = ' + json.dumps({'mode': 'static', 'basePath': base_path}) + ';\n')

    def rewrite(markup: str) -> str:
        document = html.fromstring(markup)
        for el in document.iter():
            for attr in ('href', 'src', 'action'):
                value = el.get(attr, '')
                if value.startswith('/') and not value.startswith('//'):
                    url = urlsplit(value)
                    path = url.path
                    if path != '/' and '.' not in path.rsplit('/', 1)[-1]:
                        path = path.rstrip('/') + '/'
                    el.set(attr, urlunsplit(('', '', base_path + path.lstrip('/'), url.query, url.fragment)))
        return html.tostring(document, encoding='unicode', method='html', doctype='<!doctype html>' if document.tag == 'html' else None)

    def page(path: str, markup: str):
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite(markup), encoding='utf-8')

    previous_mode = tpl.env.globals.get('static_mode')
    tpl.env.globals['static_mode'] = True
    try:
        with TestClient(app) as client:
            for path, target in [('/', 'index.html'), ('/about', 'about/index.html'), ('/shortlist', 'shortlist/index.html'), ('/missing', '404.html')]:
                page(target, client.get(path).text)
            suppliers, fragments = [], {}
            card = tpl.env.get_template('_macros.html').module.card
            for s in store.all:
                sid = s['id']
                suppliers.append(store.get(sid))
                page(f's/{sid}/index.html', client.get(f'/s/{sid}').text)
                comparison = html.fromstring(client.get('/compare', params={'ids': sid}).text)
                fragments[sid] = {
                    'card': rewrite(str(card(store.get(sid), ''))),
                    'header': rewrite(html.tostring(comparison.xpath('//table/thead/tr/th')[1], encoding='unicode')),
                    'cells': [html.tostring(td, encoding='unicode') for td in comparison.xpath('//table/tbody/tr/td')],
                }
            # A real comparison table shell: browser adds the selected columns.
            empty = html.fromstring(client.get('/compare').text)
            sample = html.fromstring(client.get('/compare', params={'ids': suppliers[0]['id']}).text)
            wrapper = sample.xpath('//div[contains(concat(" ", @class, " "), " cmp-wrap ")]')[0]
            for cell in wrapper.xpath('.//td | .//thead/tr/th[position()>1]'):
                cell.getparent().remove(cell)
            wrapper.set('hidden', '')
            main = empty.xpath('//main/div')[0]
            main.append(wrapper)
            bar = main.xpath('./div[@class="results-bar"]')[0] if main.xpath('./div[@class="results-bar"]') else main[0]
            bar.append(html.fromstring('<span class="understood" data-compare-context></span>'))
            bar.append(html.fromstring('<a class="btn small" data-export href="#" hidden>Скачать CSV</a>'))
            page('compare/index.html', html.tostring(empty, encoding='unicode'))
            dataset = {
                'meta': store.meta, 'suppliers': suppliers,
                'categories': [asdict(c) for c in CATEGORIES], 'cities': [asdict(c) for c in CITIES],
                'aliases': ALIASES, 'registry': [dict(r) for r in store.conn.execute('SELECT * FROM registry_counts')],
                'fragments': fragments,
            }
            data_path = output / 'static/dataset.json'
            data_path.write_text(json.dumps(dataset, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            print(f'Exported {len(suppliers)} suppliers; dataset {data_path.stat().st_size:,} bytes; base path {base_path}')
    finally:
        if previous_mode is None:
            tpl.env.globals.pop('static_mode', None)
        else:
            tpl.env.globals['static_mode'] = previous_mode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--base-path', default='/food-suppliers/')
    args = parser.parse_args()
    build(args.output.resolve(), args.base_path)
