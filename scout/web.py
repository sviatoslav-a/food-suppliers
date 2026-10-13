"""FastAPI app: server-rendered pages (work without JS, shareable URLs) + JSON API."""

import csv
import io
import math
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scout import rfq
from scout.service import Params, Store
from scout.taxonomy import BY_ID, CATEGORIES, CITIES, CITY_BY_ID

HERE = Path(__file__).parent
app = FastAPI(title='Scout: поиск поставщиков продуктов', version='0.1.0',
              description='Search and compare food suppliers. Data: FNS registries + supplier websites.')
app.mount('/static', StaticFiles(directory=HERE / 'static'), name='static')
tpl = Jinja2Templates(directory=HERE / 'templates')
store = Store()

LABELS = {
    'local': 'в вашем городе', 'delivers': 'доставляют к вам', 'region': 'в вашем регионе', 'other': 'другой регион',
    'micro': 'микро', 'small': 'малое', 'medium': 'среднее',
}


def fmt_rub(v) -> str:
    try:
        return f'{float(v):,.0f}'.replace(',', ' ') + ' ₽'
    except (TypeError, ValueError):
        return str(v)


tpl.env.globals.update(CATEGORIES=CATEGORIES, CITIES=CITIES, BY_ID=BY_ID, CITY_BY_ID=CITY_BY_ID, LABELS=LABELS)
tpl.env.filters['rub'] = fmt_rub


def params(q: str = '', category: str = '', city: str = '', volume_kg: str = '', certs: str = '', horeca: str = '',
           price: str = '', verified: str = '', local: str = '', sort: str = 'score') -> Params:
    def num(v: str) -> float | None:
        try:
            n = float(v.replace(',', '.')) if v else None
            return n if n is not None and math.isfinite(n) and n > 0 else None
        except ValueError:
            return None
    return Params(q=q.strip()[:200], category=category or None, city=city or None, volume_kg=num(volume_kg),
                  certs=certs.lower() in ('1', 'true', 'on'), horeca=horeca.lower() in ('1', 'true', 'on'),
                  price=price.lower() in ('1', 'true', 'on'), verified=verified.lower() in ('1', 'true', 'on'),
                  local=local.lower() in ('1', 'true', 'on'), sort=sort)


def keep_qs(p: dict) -> str:
    """Query string carrying the buyer's request to supplier/compare pages so scores stay consistent."""
    return urlencode({k: v for k, v in {'category': p.get('category'), 'city': p.get('city'),
                                        'volume_kg': p.get('volume_kg') or ''}.items() if v})


@app.get('/', response_class=HTMLResponse)
def index(request: Request, q: str = '', category: str = '', city: str = '', volume_kg: str = '', certs: str = '',
          horeca: str = '', price: str = '', verified: str = '', local: str = '', sort: str = 'score'):
    p = params(q, category, city, volume_kg, certs, horeca, price, verified, local, sort)
    searched = any([q, category, city, volume_kg, certs, horeca, price, verified, local, sort != 'score'])
    res = store.search(p) if searched else None
    ctx = {'res': res, 'p': res['params'] if res else p.__dict__, 'meta': store.meta, 'searched': searched,
           'keep': keep_qs(res['params']) if res else ''}
    if request.headers.get('x-partial') == 'results':
        return tpl.TemplateResponse(request, '_results.html', ctx)
    return tpl.TemplateResponse(request, 'index.html', ctx)


@app.get('/s/{sid}', response_class=HTMLResponse)
def supplier(request: Request, sid: str, category: str = '', city: str = '', volume_kg: str = ''):
    p = params(category=category, city=city, volume_kg=volume_kg)
    s = store.get(sid, p)
    if not s:
        raise HTTPException(404)
    draft = rfq.draft(s, p.category, p.city, f'{p.volume_kg:g} кг в неделю' if p.volume_kg else '')
    return tpl.TemplateResponse(request, 'supplier.html', {'s': s, 'p': p.__dict__, 'rfq': draft, 'keep': keep_qs(p.__dict__)})


@app.get('/compare', response_class=HTMLResponse)
def compare(request: Request, ids: str = '', category: str = '', city: str = '', volume_kg: str = ''):
    p = params(category=category, city=city, volume_kg=volume_kg)
    rows = store.compare([i for i in ids.split(',') if i], p)[:4]
    return tpl.TemplateResponse(request, 'compare.html', {'rows': rows, 'p': p.__dict__, 'keep': keep_qs(p.__dict__)})


@app.get('/shortlist', response_class=HTMLResponse)
def shortlist(request: Request):
    return tpl.TemplateResponse(request, 'shortlist.html', {})


@app.get('/about', response_class=HTMLResponse)
def about(request: Request):
    stats = {
        'suppliers': len(store.all),
        'verified': sum(s['verified_egrul'] for s in store.all),
        'with_prices': sum(bool(s['prices']) for s in store.all),
        'with_moq': sum(bool(s['moq']) for s in store.all),
        'with_delivery': sum(bool(s['delivery']) for s in store.all),
        'with_certs': sum(bool(s['certificates']) for s in store.all),
        'with_contacts': sum(bool(s['emails'] or s['phones']) for s in store.all),
        'registry': {r[0]: r[1] for r in store.conn.execute('SELECT category, sum(total) FROM registry_counts GROUP BY category')},
    }
    return tpl.TemplateResponse(request, 'about.html', {'meta': store.meta, 'stats': stats})


# ---------- JSON API ----------

@app.get('/api/search')
def api_search(q: str = '', category: str = '', city: str = '', volume_kg: str = '', certs: str = '', horeca: str = '',
               price: str = '', verified: str = '', local: str = '', sort: str = 'score', limit: int = Query(50, ge=1, le=200)):
    res = store.search(params(q, category, city, volume_kg, certs, horeca, price, verified, local, sort))
    res['results'] = res['results'][:limit]
    return res


@app.get('/api/suppliers')
def api_suppliers(ids: str = '', category: str = '', city: str = '', volume_kg: str = ''):
    return store.compare([i for i in ids.split(',') if i], params(category=category, city=city, volume_kg=volume_kg)) if ids else []


@app.get('/api/suppliers/{sid}')
def api_supplier(sid: str, category: str = '', city: str = '', volume_kg: str = ''):
    s = store.get(sid, params(category=category, city=city, volume_kg=volume_kg))
    if not s:
        raise HTTPException(404, 'supplier not found')
    return s


@app.get('/api/rfq/{sid}')
def api_rfq(sid: str, category: str = '', city: str = '', volume: str = '', company: str = ''):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, 'supplier not found')
    return rfq.draft(s, category or None, city or None, volume, company)


def csv_safe(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else value


@app.get('/api/export.csv')
def export_csv(ids: str = '', category: str = '', city: str = ''):
    rows = store.compare([i for i in ids.split(',') if i], params(category=category, city=city)) if ids else []
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['Поставщик', 'Юрлицо', 'ИНН', 'Город', 'Сайт', 'Телефон', 'Email', 'Оценка', 'Мин. заказ', 'Доставка',
                'Цены', 'Документы', 'Следующий шаг'])
    for s in rows:
        w.writerow([csv_safe(v) for v in [s['name'], s['legal_name'] or '', s['inn'] or '', s['home_city'] or '', s['website'],
                    ', '.join(x['value'] for x in s['phones']), ', '.join(x['value'] for x in s['emails']), s['score'],
                    (s['moq'] or {}).get('text', ''), (s['delivery'] or {}).get('text', ''),
                    '; '.join(f'{x["product"]}: {x["price"]} ₽/{x.get("unit", "")}' for x in s['prices']),
                    '; '.join(x['text'] for x in s['certificates']), s['next_action']]])
    data = '﻿' + buf.getvalue()  # BOM so Excel opens Cyrillic correctly
    return StreamingResponse(iter([data]), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': 'attachment; filename="suppliers.csv"'})


@app.get('/api/stats')
def api_stats():
    return {'meta': store.meta, 'suppliers': len(store.all)}


@app.get('/healthz')
def health():
    return {'ok': True, 'suppliers': len(store.all)}


@app.exception_handler(404)
def not_found(request: Request, exc):
    if request.url.path.startswith('/api/'):
        return JSONResponse({'detail': getattr(exc, 'detail', 'not found')}, status_code=404)
    return tpl.TemplateResponse(request, '404.html', {}, status_code=404)
