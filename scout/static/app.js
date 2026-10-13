// Progressive enhancement for Scout. Pages work without JS; this adds live filtering,
// shortlist/compare state (localStorage), RFQ helpers and the shortlist board.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const MAX_COMPARE = 4;
const STATUSES = [['new', 'Новый'], ['sent', 'Запрос отправлен'], ['quote', 'Получено КП'], ['deal', 'Договор'], ['no', 'Отказ']];

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch {} },
};
const shortlist = () => store.get('scout.shortlist', {});
const compareIds = () => store.get('scout.compare', []);
const lastQuery = () => store.get('scout.last', '');

function toast(msg) {
  const t = $('[data-toast]');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove('on'), 1800);
}

/* ---------- shared state rendering ---------- */
function keepQs() {
  const p = new URLSearchParams($('[data-context]')?.dataset.context || lastQuery());
  const out = new URLSearchParams();
  for (const k of ['category', 'city', 'volume_kg']) if (p.get(k)) out.set(k, p.get(k));
  return out.toString();
}
function compareHref(ids = compareIds()) {
  const k = keepQs();
  return `/compare?ids=${ids.join(',')}${k ? '&' + k : ''}`;
}
function syncUI() {
  const sl = shortlist(), cmp = compareIds();
  for (const [key, n] of [['shortlist', Object.keys(sl).length], ['compare', cmp.length]]) {
    $$(`[data-count="${key}"]`).forEach((el) => { el.textContent = n; el.dataset.n = n; });
  }
  $$('[data-shortlist]').forEach((b) => {
    const on = !!sl[b.dataset.shortlist];
    b.setAttribute('aria-pressed', on);
    b.textContent = on ? '★ В шорт-листе' : '☆ В шорт-лист';
  });
  $$('[data-compare]').forEach((b) => {
    const on = cmp.includes(b.dataset.compare);
    b.setAttribute('aria-pressed', on);
    b.textContent = on ? '✓ К сравнению' : '⇄ Сравнить';
    b.closest('.sup')?.classList.toggle('selected', on);
  });
  const tray = $('[data-tray]');
  if (tray) {
    const show = cmp.length > 0 && document.body.dataset.page !== 'compare';
    tray.classList.toggle('on', show);
    tray.setAttribute('aria-hidden', String(!show));
    $('[data-tray-n]').textContent = cmp.length;
    $('[data-tray-go]').href = compareHref();
    $('[data-tray-go]').toggleAttribute('aria-disabled', cmp.length < 2);
  }
  const nav = $('[data-nav-compare]');
  if (nav) nav.href = compareHref();
}

function nameFor(id) {
  return document.querySelector(`[data-id="${id}"]`)?.dataset.name || $('[data-supplier]')?.dataset.name || id;
}

function toggleShortlist(id) {
  const sl = shortlist();
  if (sl[id]) { delete sl[id]; toast('Убрано из шорт-листа'); }
  else { sl[id] = { name: nameFor(id), status: 'new', note: '', quote: {}, added: new Date().toISOString().slice(0, 10) }; toast('Добавлено в шорт-лист'); }
  store.set('scout.shortlist', sl);
  syncUI();
}
function toggleCompare(id) {
  let ids = compareIds();
  if (ids.includes(id)) ids = ids.filter((x) => x !== id);
  else if (ids.length >= MAX_COMPARE) { toast(`Сравнивать можно до ${MAX_COMPARE} поставщиков`); return; }
  else ids = [...ids, id];
  store.set('scout.compare', ids);
  syncUI();
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('button, a');
  if (!t) return;
  if (t.dataset.shortlist) toggleShortlist(t.dataset.shortlist);
  else if (t.dataset.compare) toggleCompare(t.dataset.compare);
  else if (t.matches('[data-tray-clear]')) { store.set('scout.compare', []); syncUI(); }
  else if (t.matches('[data-tray-go]') && compareIds().length < 2) { e.preventDefault(); toast('Добавьте ещё хотя бы одного поставщика'); }
  else if (t.matches('[data-theme-toggle]')) {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('scout.theme', next); } catch {}
  }
});

/* ---------- search page: live filtering ---------- */
function initSearch() {
  const form = $('[data-search]');
  const box = $('[data-results]');
  if (!form || !box) return;
  let ctrl;
  const run = async (push = false) => {
    const qs = new URLSearchParams(new FormData(form));
    for (const [k, v] of [...qs]) if (!v || (k === 'sort' && v === 'score')) qs.delete(k);
    const url = '/' + (qs.toString() ? '?' + qs : '');
    if (!qs.toString()) { location.href = '/'; return; }
    ctrl?.abort();
    ctrl = new AbortController();
    const current = ctrl;
    box.classList.add('loading');
    try {
      const r = await fetch(url, { headers: { 'x-partial': 'results' }, signal: ctrl.signal });
      if (!r.ok) throw new Error('Search failed');
      const html = await r.text();
      if (current.signal.aborted) return;
      box.innerHTML = html;
      history[push ? 'pushState' : 'replaceState'](null, '', url);
      store.set('scout.last', qs.toString());
      syncUI();
      $('.examples', form)?.remove();
    } catch (err) {
      if (err.name !== 'AbortError') form.submit();
    } finally {
      if (ctrl === current) box.classList.remove('loading');
    }
  };
  form.addEventListener('submit', (e) => { e.preventDefault(); run(true); });
  form.addEventListener('change', (e) => { if (e.target.name !== 'q') run(); });
  let t;
  form.querySelector('[name="volume_kg"]')?.addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 450); });
  box.addEventListener('change', (e) => {
    if (e.target.matches('[data-sort]')) { form.querySelector('[name="sort"]').value = e.target.value; run(); }
  });
  addEventListener('popstate', () => location.reload());
  if (location.search) store.set('scout.last', location.search.slice(1));
}

/* ---------- supplier page ---------- */
function initSupplier() {
  const root = $('[data-supplier]');
  if (!root) return;
  const id = root.dataset.supplier;
  const back = $('[data-back]');
  if (back && lastQuery()) back.href = '/?' + lastQuery();

  const entry = () => shortlist()[id] || { name: root.dataset.name, status: 'new', note: '', quote: {}, added: new Date().toISOString().slice(0, 10) };
  const save = (patch, msg = 'Сохранено') => {
    const sl = shortlist();
    sl[id] = { ...entry(), ...patch };
    store.set('scout.shortlist', sl);
    const s = $('[data-saved]');
    if (s) { s.textContent = msg + ' · в шорт-листе'; clearTimeout(save.t); save.t = setTimeout(() => (s.textContent = ''), 2500); }
    render();
    syncUI();
  };
  const render = () => {
    const e = shortlist()[id];
    $$('[data-status]').forEach((b) => b.setAttribute('aria-pressed', String(!!e && e.status === b.dataset.status)));
    const note = $('[data-note]');
    if (note && document.activeElement !== note) note.value = e?.note || '';
    $$('[data-quote]').forEach((i) => { if (document.activeElement !== i) i.value = e?.quote?.[i.dataset.quote] || ''; });
    const mine = $('[data-mine="moq"]');
    if (mine) mine.innerHTML = e?.quote?.moq ? `<br>из КП: ${escapeHtml(e.quote.moq)} <span class="src me">вы</span>` : '';
  };
  $$('[data-status]').forEach((b) => b.addEventListener('click', () => save({ status: b.dataset.status }, 'Статус обновлён')));
  $('[data-note]')?.addEventListener('input', (e) => save({ note: e.target.value }));
  $$('[data-quote]').forEach((i) => i.addEventListener('input', () => {
    save({ quote: { ...entry().quote, [i.dataset.quote]: i.value } });
  }));

  const subj = $('[data-rfq-subject]'), body = $('[data-rfq-body]'), mail = $('[data-mailto]');
  const updateMail = () => {
    if (mail) mail.href = `mailto:${mail.href.split(':')[1].split('?')[0]}?subject=${encodeURIComponent(subj.value)}&body=${encodeURIComponent(body.value)}`;
  };
  subj?.addEventListener('input', updateMail);
  body?.addEventListener('input', updateMail);
  updateMail();
  $('[data-copy-rfq]')?.addEventListener('click', async () => {
    const text = `${subj.value}\n\n${body.value}`;
    try { await navigator.clipboard.writeText(text); } catch { body.select(); document.execCommand?.('copy'); }
    toast('Письмо скопировано');
  });
  $('[data-rfq-sent]')?.addEventListener('click', () => save({ status: 'sent' }, 'Отмечено: запрос отправлен'));
  render();
}

/* ---------- compare page ---------- */
function initCompare() {
  if (document.body.dataset.page !== 'compare') return;
  const params = new URLSearchParams(location.search);
  if (!params.has('ids') && compareIds().length) { location.replace(compareHref()); return; }
  if (params.has('ids')) store.set('scout.compare', [...new Set(params.get('ids').split(',').filter(Boolean))].slice(0, MAX_COMPARE));
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove]');
    if (!b) return;
    const ids = compareIds().filter((x) => x !== b.dataset.remove);
    store.set('scout.compare', ids);
    ids.length ? location.replace(compareHref(ids)) : location.replace('/compare?ids=');
  });
  syncUI();
}

/* ---------- shortlist board ---------- */
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]); }

async function initShortlist() {
  const board = $('[data-board]');
  if (!board) return;
  const sl = shortlist();
  const ids = Object.keys(sl);
  const exp = $('[data-sl-export]'), cmp = $('[data-sl-compare]');
  if (!ids.length) {
    board.replaceWith($('[data-empty-tpl]').content.cloneNode(true));
    exp?.remove(); cmp?.remove();
    return;
  }
  exp.href = `/api/export.csv?ids=${ids.join(',')}`;
  exp.setAttribute('download', 'shortlist.csv');
  cmp.href = compareHref(ids.slice(0, MAX_COMPARE));
  cmp.addEventListener('click', () => store.set('scout.compare', Object.keys(shortlist()).slice(0, MAX_COMPARE)));
  let data = [];
  try { data = await (await fetch(`/api/suppliers?ids=${ids.join(',')}&${keepQs()}`)).json(); } catch {}
  const byId = Object.fromEntries(data.map((s) => [s.id, s]));
  exp.addEventListener('click', (event) => {
    event.preventDefault();
    const cell = (value) => {
      let text = String(value ?? '');
      if (/^[\s]*[=+@-]/.test(text)) text = "'" + text;
      return '"' + text.replaceAll('"', '""') + '"';
    };
    const rows = [['Поставщик', 'Сайт', 'Контакты', 'Оценка', 'Статус', 'Заметка', 'Цена из КП (вы)', 'Мин. заказ из КП (вы)']];
    for (const [id, entry] of Object.entries(shortlist())) {
      const supplier = byId[id];
      rows.push([supplier?.name || entry.name || id, supplier?.website || '',
        [...(supplier?.emails || []), ...(supplier?.phones || [])].map(x => x.value).join(', '),
        supplier?.score ?? '', STATUSES.find(([s]) => s === entry.status)?.[1] || 'Новый',
        entry.note, entry.quote?.price, entry.quote?.moq]);
    }
    const blob = new Blob(['\ufeff' + rows.map(row => row.map(cell).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'shortlist.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const draw = () => {
    const cur = shortlist();
    const currentIds = Object.keys(cur);
    exp.href = `/api/export.csv?ids=${currentIds.join(',')}&${keepQs()}`;
    cmp.href = compareHref(currentIds.slice(0, MAX_COMPARE));
    board.className = 'board';
    board.innerHTML = STATUSES.map(([st, label]) => {
      const items = Object.entries(cur).filter(([, e]) => (e.status || 'new') === st);
      return `<section class="col" data-col="${st}"><h3>${label}<span class="muted mono">${items.length}</span></h3>${items.map(([id, e]) => {
        const s = byId[id];
        return `<article class="mini" data-item="${id}">
          <a class="name" href="/s/${id}">${escapeHtml(s?.name || e.name || id)}</a>
          ${s ? `<p>${s.score}/100 · ${escapeHtml(s.emails?.[0]?.value || s.phones?.[0]?.value || s.website)}</p>` : '<p class="muted">нет в текущей базе</p>'}
          ${e.quote?.price || e.quote?.moq ? `<p>КП: ${escapeHtml([e.quote.price, e.quote.moq].filter(Boolean).join(', '))}</p>` : ''}
          ${e.note ? `<p>${escapeHtml(e.note)}</p>` : ''}
          <label class="sr-only" for="st-${id}">Статус</label>
          <select id="st-${id}" data-move="${id}">${STATUSES.map(([v, l]) => `<option value="${v}" ${v === st ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <button class="btn small ghost" type="button" data-shortlist="${id}" style="margin-top:6px;width:100%">Убрать</button>
        </article>`;
      }).join('')}</section>`;
    }).join('');
  };
  board.addEventListener('change', (e) => {
    const id = e.target.dataset.move;
    if (!id) return;
    const s = shortlist();
    s[id].status = e.target.value;
    store.set('scout.shortlist', s);
    draw();
    toast('Статус обновлён');
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-board] [data-shortlist]')) setTimeout(() => (Object.keys(shortlist()).length ? draw() : location.reload()), 0);
  });
  draw();
}

initSearch();
initSupplier();
initCompare();
initShortlist();
syncUI();
