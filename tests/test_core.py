from datetime import date

from pipeline.fetch import facts, norm_phone, pick_links
from scout.query import parse
from scout.rfq import draft
from scout.scoring import Request, next_action, score, serves_city, years_since


def sup(**kw):
    base = dict(id='x', name='X', categories=['dairy'], products=['моцарелла'], moq=None, prices=[], delivery=None,
                service_area=None, certificates=[], phones=[], emails=[], red_flags=[], horeca=False, b2b=True,
                verified_egrul=False, verified_registry=False, status='', reg_date=None, sme=None, city='', home_city='',
                region_code='')
    return base | kw


# ---- query parser
def test_parse_full_sentence():
    p = parse('Сыры для пиццы в Екатеринбурге с документами, заказ 30 кг')
    assert (p.category, p.city, p.certs, p.volume_kg) == ('dairy', 'ekb', True, 30)


def test_parse_aliases_and_units():
    assert parse('молочка екб').category == 'dairy'
    assert parse('упаковка для доставки Москва').city == 'msk'
    assert parse('лосось для суши').category in ('fish', 'asian')
    assert parse('мука 1,5 т').volume_kg == 1500
    assert parse('бюджет 20 тыс руб').volume_rub == 20000


def test_parse_nothing():
    p = parse('привет')
    assert p.category is None and p.city is None and not p.certs


# ---- scoring
def test_local_verified_complete_supplier_beats_unknown():
    good = sup(home_city='Екатеринбург', verified_egrul=True, status='active', reg_date='01.01.2015', sme='small',
               certificates=[{'text': 'декларации', 'source': 'u'}], horeca=True,
               prices=[{'product': 'a', 'price': 1, 'unit': 'кг', 'source': 'u'}],
               moq={'text': 'от 5000 ₽', 'rub': 5000, 'source': 'u'}, delivery={'text': 'завтра', 'source': 'u'})
    bad = sup(home_city='Казань', b2b=False)
    r = Request('dairy', 'ekb')
    g, gp = score(good, r, today=date(2026, 10, 13))
    b, _ = score(bad, r, today=date(2026, 10, 13))
    assert g >= 95 and b < 45
    assert {p.key for p in gp} >= {'category', 'geo', 'reliability', 'docs', 'terms', 'horeca'}


def test_moq_above_volume_is_penalised_and_explained():
    s = sup(moq={'text': 'от 100 кг', 'kg': 100, 'source': 'u'})
    base, _ = score(s, Request('dairy', None))
    pen, parts = score(s, Request('dairy', None, volume_kg=30))
    assert pen == base - 15
    assert any('100 кг больше' in p.why for p in parts)


def test_geography_levels():
    assert serves_city(sup(home_city='г. Екатеринбург'), 'ekb')[0] == 'local'
    assert serves_city(sup(service_area={'text': 'доставка по Екатеринбургу и области', 'cities': []}), 'ekb')[0] == 'delivers'
    assert serves_city(sup(region_code='66'), 'ekb')[0] == 'region'
    assert serves_city(sup(home_city='Казань'), 'ekb')[0] == 'other'
    assert serves_city(sup(service_area={'text': 'только наш регион', 'cities': []}), 'ekb')[0] == 'other'
    assert serves_city(sup(service_area={'text': 'доставка по всей России', 'cities': []}), 'ekb')[0] == 'delivers'


def test_age():
    assert round(years_since('13.10.2016', date(2026, 10, 13))) == 10
    assert years_since('bad') is None


def test_next_action_asks_for_missing():
    assert 'запросить прайс' in next_action(sup(emails=[{'value': 'opt@x.ru'}]))
    assert next_action(sup(emails=[{'value': 'opt@x.ru'}])).startswith('Написать на opt@x.ru')


# ---- RFQ
def test_rfq_asks_only_for_missing():
    d = draft(sup(prices=[{'product': 'a'}], emails=[{'value': 'opt@x.ru'}]), 'dairy', 'ekb', '30 кг в неделю')
    assert d['to'] == 'opt@x.ru' and 'Екатеринбург' in d['subject']
    assert 'прайс' not in d['body'] and 'минимальную' in d['body'] and '30 кг' in d['body']


# ---- crawler facts
def test_facts_regexes_keep_sources_and_skip_personal_mail():
    pages = {'https://x.ru/contacts': {'text': 'ИНН 6685159671 КПП 1 тел 8 (343) 379-55-90 opt@x.ru ivan.petrov@x.ru'}}
    f = facts(pages)
    assert f['inn'] == [{'value': '6685159671', 'source': 'https://x.ru/contacts'}]
    assert f['phones'][0]['value'] == '+7 (343) 379-55-90'
    assert [e['value'] for e in f['emails']] == ['opt@x.ru']


def test_norm_phone():
    assert norm_phone('8-343-379-55-90') == '+7 (343) 379-55-90'


def test_pick_links_same_host_and_priority():
    links = [('/catalog', 'Каталог'), ('https://other.ru/kontakty', 'Контакты'), ('/kontakty', 'Контакты'), ('/x.pdf', 'Прайс')]
    assert pick_links('https://x.ru/', links) == ['https://x.ru/kontakty', 'https://x.ru/catalog']
