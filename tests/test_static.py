"""Run the same browser journeys under a GitHub Pages-style subpath, without FastAPI."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest
from playwright.sync_api import expect

from scout.service import Params, Store
from tools.build_pages import build
from test_e2e import (
    app_page, supplier_records,
    test_search_filter_sort_empty_and_history,
    test_compare_limit_context_and_remove,
    test_shortlist_quotes_persistence_and_export,
    test_rfq_edit_copy_and_explicit_sent,
    test_responsive_pages,
    test_no_javascript_search_and_supplier,
)


@pytest.fixture(scope='module')
def static_mode():
    return True


@pytest.fixture(scope='module')
def live_url(tmp_path_factory):
    root = tmp_path_factory.mktemp('pages')
    build(root / 'food-suppliers', '/food-suppliers/')
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/food-suppliers'
    server.shutdown()
    server.server_close()
    thread.join()


def test_static_no_backend_and_deep_links(page, live_url):
    requests = []
    page.on('request', lambda r: requests.append(r.url))
    page.goto(live_url + '/?category=dairy&city=ekb&volume_kg=30')
    expect(page.locator('html')).to_have_attribute('data-ready', 'true')
    expect(page.locator('.sup').first).to_be_visible()
    link = page.locator('.sup h3 a').first
    supplier_url = link.get_attribute('href')
    score = page.locator('.sup .score b').first.inner_text()
    link.click()
    expect(page.locator('html')).to_have_attribute('data-ready', 'true')
    expect(page.locator('.sp-head .score b')).to_have_text(score)
    assert '30 кг в неделю' in page.locator('[data-rfq-body]').input_value()
    page.reload()
    expect(page.locator('html')).to_have_attribute('data-ready', 'true')
    expect(page.locator('.sp-head .score b')).to_have_text(score)
    assert '/food-suppliers/s/' in supplier_url
    assert not any('/api/' in url or 'ts.net' in url for url in requests)
    for link in page.locator('a[href]').all():
        href = link.get_attribute('href')
        assert not href.startswith('/') or href.startswith('/food-suppliers/'), href


def test_static_search_parity(page, live_url):
    page.goto(live_url + '/')
    expect(page.locator('html')).to_have_attribute('data-ready', 'true')
    store = Store()
    queries = ['', 'q=zzzxxyyunknownsupplier', 'q=Гросс', 'q=сыр', 'q=молочка+екб+заказ+30+кг',
               'q=сыры+для+пиццы+в+Екатеринбурге+с+документами', 'category=packaging&city=msk',
               'category=dairy&city=ekb&volume_kg=30&sort=complete', 'city=msk&local=1',
               'verified=1&price=1&horeca=1', 'sort=age', 'sort=name']
    from scout.web import params
    from urllib.parse import parse_qsl
    for query in queries:
        expected = store.search(params(**dict(parse_qsl(query))))
        actual = page.evaluate("""async query => {
          const {source} = await import('./static/data-source.js');
          const result = (await source()).search(query);
          return {ids: result.results.map(s => s.id), scores: result.results.map(s => s.score), params:result.params};
        }""", query)
        assert actual['ids'] == [s['id'] for s in expected['results']], query
        assert actual['scores'] == [s['score'] for s in expected['results']], query
        assert actual['params'] == expected['params'], query


def test_static_comparison_csv(page, live_url):
    page.goto(live_url + '/compare/?ids=ekat-grossfood-ru,sobolevcheese-ru&category=dairy&city=ekb')
    expect(page.locator('html')).to_have_attribute('data-ready', 'true')
    expect(page.locator('[data-remove]')).to_have_count(2)
    with page.expect_download() as download:
        page.locator('[data-export]').click()
    from pathlib import Path
    text = Path(download.value.path()).read_text(encoding='utf-8-sig')
    assert 'Гросс' in text and 'Соболев' in text


def test_static_load_error(page, live_url):
    page.route('**/static/dataset.json', lambda route: route.fulfill(status=503, body='Unavailable'))
    page.goto(live_url + '/')
    expect(page.get_by_role('alert')).to_contain_text('Не удалось загрузить базу')
