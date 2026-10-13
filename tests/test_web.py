"""Acceptance checks against the bundled real-data snapshot; no network needed."""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from pipeline.build import eligible
from scout.service import Params
from scout.web import app, csv_safe, params, store

client = TestClient(app)


@pytest.mark.parametrize('url', ['/', '/about', '/compare', '/shortlist', '/docs', '/healthz',
                                      '/?volume_kg=30', '/?category=dairy&city=ekb'])
def test_pages(url):
    assert client.get(url).status_code == 200


def test_every_supplier_card_and_sources():
    for supplier in store.all:
        assert client.get('/s/' + supplier['id']).status_code == 200
        for field in ('phones', 'emails', 'prices', 'certificates'):
            for fact in supplier[field]:
                assert fact['source'] in supplier['pages'], (supplier['id'], field, fact)


def test_search_filters_and_empty_query():
    result = client.get('/api/search', params={'category': 'dairy', 'city': 'ekb', 'certs': '1'}).json()
    assert result['total'] > 0
    assert all(s['certificates'] for s in result['results'])
    assert result['results'] == sorted(result['results'], key=lambda s: (-s['score'], -s['text_hit'], s['name']))
    assert client.get('/api/search?q=zzzxxyyunknownsupplier').json()['total'] == 0
    assert client.get('/api/search?certs=false').json()['total'] == len(store.all)
    assert client.get('/api/search?limit=-1').status_code == 422


def test_export_and_shortlist_are_not_limited_to_four():
    ids = [s['id'] for s in store.all[:7]]
    response = client.get('/api/suppliers', params={'ids': ','.join(ids)})
    assert len(response.json()) == 7
    export = client.get('/api/export.csv', params={'ids': ','.join(ids)})
    rows = list(csv.reader(io.StringIO(export.text.lstrip('\ufeff')), delimiter=';'))
    assert len(rows) == 8
    assert rows[0][0] == 'Поставщик'
    assert len(store.compare(ids + ids)) == 7


def test_score_context_consistent():
    sid = store.all[0]['id']
    args = {'category': 'dairy', 'city': 'ekb', 'volume_kg': '1'}
    single = client.get('/api/suppliers/' + sid, params=args).json()
    listed = client.get('/api/suppliers', params={'ids': sid, **args}).json()[0]
    assert single['score'] == listed['score']


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', 'bad', '0'])
def test_invalid_volume(value):
    assert params(volume_kg=value).volume_kg is None
    assert client.get('/api/search', params={'volume_kg': value}).status_code == 200


def test_missing_supplier():
    assert client.get('/s/missing').status_code == 404
    assert client.get('/api/suppliers/missing').status_code == 404
    assert client.get('/api/rfq/missing').status_code == 404


def test_rfq_is_draft_only():
    sid = store.all[0]['id']
    r = client.get('/api/rfq/' + sid, params={'category': 'dairy', 'city': 'ekb', 'volume': '30 кг'}).json()
    assert '30 кг' in r['body']
    assert r['subject']


def test_csv_formula_safety():
    for text in ('=HYPERLINK("x")', '+123', '-1', '@SUM(A1)', '  =1'):
        assert csv_safe(text).startswith("'")
    assert csv_safe('Сыр') == 'Сыр'


def test_packaging_eligibility():
    assert eligible({'kind': 'not_food', 'b2b': True, 'categories': ['packaging'], 'description': 'Одноразовая посуда'})
    assert not eligible({'kind': 'not_food', 'b2b': True, 'categories': ['packaging'], 'description': 'Пакеты для бутиков'})
    assert not eligible({'kind': 'retail', 'b2b': False})


def test_mcp_tools_share_service():
    from scout.mcp_server import search_suppliers, get_supplier, draft_request, taxonomy
    r = search_suppliers(category='dairy', city='ekb', limit=3)
    assert 0 < len(r['suppliers']) <= 3
    sid = r['suppliers'][0]['id']
    assert get_supplier(sid)['id'] == sid
    assert draft_request(sid)['subject']
    assert 'packaging' in taxonomy()
