"""Real Chromium user journeys. Run: uv run pytest tests/test_e2e.py -q."""
import csv
import io
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect


@pytest.fixture(scope='module')
def live_url():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'scout.web:app', '--host', '127.0.0.1', '--port', str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if httpx.get(url + '/healthz').status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(.1)
        else:
            raise RuntimeError('Test server did not start')
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def app_page(page, live_url):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(live_url)
    expect(page.locator('[data-tray]')).not_to_be_visible()
    yield page
    assert not errors, errors


def test_search_filter_sort_empty_and_history(app_page, live_url):
    page = app_page
    page.locator('[name=q]').fill('сыры для пиццы в Екатеринбурге с документами')
    page.get_by_role('button', name='Найти', exact=True).click()
    expect(page.locator('[data-f=category]')).to_contain_text('Молоч')
    expect(page.locator('[data-f=city]')).to_contain_text('Екатеринбург')
    expect(page.locator('.sup').first).to_be_visible()
    page.locator('[data-sort]').select_option('name')
    expect(page).to_have_url(__import__('re').compile('.*sort=name.*'))
    page.goto(live_url + '/?q=zzzxxyyunknownsupplier')
    expect(page.locator('[data-empty]')).to_be_visible()
    page.go_back()
    expect(page.locator('.sup').first).to_be_visible()


def test_compare_limit_context_and_remove(app_page):
    page = app_page
    page.locator('[name=q]').fill('молочка екб заказ 30 кг')
    page.get_by_role('button', name='Найти', exact=True).click()
    expect(page.locator('.sup').first).to_be_visible()
    buttons = page.locator('[data-compare]')
    for i in range(5):
        buttons.nth(i).click()
    assert page.evaluate("JSON.parse(localStorage.getItem('scout.compare')).length") == 4
    href = page.locator('[data-tray-go]').get_attribute('href')
    assert 'category=dairy' in href and 'city=ekb' in href and 'volume_kg=30' in href
    page.locator('[data-tray-go]').click()
    expect(page.locator('[data-remove]')).to_have_count(4)
    for left in range(3, -1, -1):
        page.locator('[data-remove]').first.click()
        expect(page.locator('[data-remove]')).to_have_count(left)
    assert page.evaluate("JSON.parse(localStorage.getItem('scout.compare'))") == []


def test_shortlist_quotes_persistence_and_export(app_page, live_url):
    page = app_page
    page.goto(live_url + '/?category=dairy')
    expect(page.locator('.sup').first).to_be_visible()
    ids = []
    for i in range(6):
        button = page.locator('[data-shortlist]').nth(i)
        ids.append(button.get_attribute('data-shortlist'))
        button.click()
    page.goto(live_url + '/s/' + ids[0])
    page.locator('[data-note]').fill('Позвонить в пятницу')
    page.locator('[data-quote=price]').fill('350 ₽/кг')
    page.locator('[data-quote=moq]').fill('10 кг')
    page.locator('[data-status=quote]').click()
    page.reload()
    expect(page.locator('[data-note]')).to_have_value('Позвонить в пятницу')
    expect(page.locator('[data-quote=price]')).to_have_value('350 ₽/кг')
    expect(page.locator('[data-quote=moq]')).to_have_value('10 кг')
    expect(page.locator('[data-status=quote]')).to_have_attribute('aria-pressed', 'true')
    page.goto(live_url + '/shortlist')
    expect(page.locator('[data-item]')).to_have_count(6)
    expect(page.locator(f'[data-col=quote] [data-item="{ids[0]}"]')).to_be_visible()
    assert 'нет в текущей базе' not in page.locator('[data-board]').inner_text()
    page.locator(f'[data-move="{ids[0]}"]').select_option('deal')
    expect(page.locator(f'[data-col=deal] [data-item="{ids[0]}"]')).to_be_visible()
    page.locator(f'[data-shortlist="{ids[-1]}"]').click()
    expect(page.locator('[data-item]')).to_have_count(5)
    with page.expect_download() as info:
        page.locator('[data-sl-export]').click()
    rows = list(csv.reader(io.StringIO(Path(info.value.path()).read_text(encoding='utf-8-sig')), delimiter=';'))
    assert len(rows) == 6  # header plus ALL five remaining suppliers
    assert 'Позвонить в пятницу' in rows[1]
    assert '350 ₽/кг' in rows[1]
    assert '10 кг' in rows[1]
    assert 'Договор' in rows[1]
    href = page.locator('[data-sl-compare]').get_attribute('href')
    assert ids[-1] not in href


def test_rfq_edit_copy_and_explicit_sent(app_page, live_url, context):
    page = app_page
    suppliers = httpx.get(live_url + '/api/search?limit=200').json()['results']
    sid = next(s['id'] for s in suppliers if s['emails'])
    page.goto(live_url + '/s/' + sid)
    page.locator('[data-rfq-subject]').fill('Запрос на поставку')
    expect(page.locator('[data-mailto]')).to_have_attribute('href', __import__('re').compile('mailto:.*subject=.*'))
    assert page.evaluate("localStorage.getItem('scout.shortlist')") is None
    context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.locator('[data-copy-rfq]').click()
    assert 'Запрос на поставку' in page.evaluate('navigator.clipboard.readText()')
    page.locator('[data-rfq-sent]').click()
    expect(page.locator('[data-status=sent]')).to_have_attribute('aria-pressed', 'true')
    page.reload()
    expect(page.locator('[data-status=sent]')).to_have_attribute('aria-pressed', 'true')


@pytest.mark.parametrize('width', [390, 1440])
def test_responsive_pages(app_page, live_url, width):
    page = app_page
    page.set_viewport_size({'width': width, 'height': 900})
    for path in ('/', '/?category=packaging&city=msk', '/about', '/shortlist'):
        page.goto(live_url + path)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), path
    page.goto(live_url + '/?category=dairy')
    sid = page.locator('[data-shortlist]').first.get_attribute('data-shortlist')
    page.goto(live_url + '/s/' + sid)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.locator('[data-theme-toggle]').click()
    theme = page.evaluate('document.documentElement.dataset.theme')
    page.reload()
    assert page.evaluate('document.documentElement.dataset.theme') == theme
    Path('test-results').mkdir(exist_ok=True)
    page.screenshot(path=f'test-results/supplier-{width}.png', full_page=True)


def test_no_javascript_search_and_supplier(browser, live_url):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        page.goto(live_url)
        page.locator('[name=q]').fill('молочка екб')
        page.get_by_role('button', name='Найти', exact=True).click()
        expect(page.locator('.sup').first).to_be_visible()
        sid = page.locator('[data-shortlist]').first.get_attribute('data-shortlist')
        page.goto(live_url + '/s/' + sid)
        expect(page.locator('[data-rfq-body]')).not_to_be_empty()
    finally:
        context.close()
