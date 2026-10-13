// Browser search over the public snapshot exported by tools/build_pages.py.
// Invariant facts and HTML come from the Python service and Jinja templates.
import { appUrl } from './data-source.js';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const has = value => Array.isArray(value) ? value.length > 0 : !!value;
const roundEven = n => Math.abs(n % 1) === .5 ? 2 * Math.round(n / 2) : Math.round(n);
const compareText = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const labels = { local: 'в вашем городе', delivers: 'доставляют к вам', region: 'в вашем регионе', other: 'другой регион' };
const number = value => { const n = Number(String(value || '').replace(',', '.')); return Number.isFinite(n) && n > 0 ? n : null; };
const context = p => new URLSearchParams(Object.entries(p).filter(([k,v]) => ['category','city','volume_kg'].includes(k) && v)).toString();

export class StaticSource {
  constructor(data) {
    Object.assign(this, data);
    this.byId = Object.fromEntries(this.suppliers.map(s => [s.id, s]));
    this.categoriesById = Object.fromEntries(this.categories.map(c => [c.id, c]));
    this.citiesById = Object.fromEntries(this.cities.map(c => [c.id, c]));
    // FTS5-compatible token frequencies and document lengths for prefix BM25.
    this.documents = this.suppliers.map(s => {
      const words = [s.name, s.description, JSON.stringify(s.products)].join(' ').toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').match(/[\p{L}\p{N}_]+/gu) || [];
      return { id: s.id, words };
    });
    this.averageLength = this.documents.reduce((n,d) => n + d.words.length, 0) / this.documents.length;
  }

  resolve(query = '') {
    const raw = typeof query === 'string' ? Object.fromEntries(new URLSearchParams(query)) : query;
    const p = { q: String(raw.q || '').trim().slice(0,200), category: raw.category || null, city: raw.city || null,
      volume_kg: number(raw.volume_kg), volume_rub: null, sort: raw.sort || 'score', parsed: [] };
    for (const key of ['certs','horeca','price','verified','local']) p[key] = ['1','true','on'].includes(String(raw[key] || '').toLowerCase());
    if (p.q) {
      const text = ' ' + p.q.toLowerCase().replaceAll('ё','е') + ' ';
      let category = null, city = null, matched = [];
      for (const [alias,id] of Object.entries(this.aliases)) if (text.includes(alias)) { category = id; matched.push(alias); break; }
      if (!category) {
        let best = 0;
        for (const c of this.categories) {
          const hits = c.words.filter(w => text.includes(w));
          if (hits.length > best) { best = hits.length; category = c.id; matched = hits; }
        }
      }
      for (const c of this.cities) {
        const hit = c.words.find(w => text.includes(w));
        if (hit) { city = c.id; matched.push(hit); break; }
      }
      p.category ||= category; p.city ||= city; p.parsed = matched;
      p.certs ||= /сертифик|деклараци|документ|ветеринар|меркурий|халяль|хассп|haccp/.test(text);
      p.horeca ||= /horeca|хорека|ресторан|общепит|кафе/.test(text);
      p.price ||= /прайс|цен[аыу]|стоимост/.test(text);
      const kg = text.match(/(\d+(?:[.,]\d+)?)\s*(кг|килограмм|т(?=\s|$)|тонн)/);
      if (kg && !p.volume_kg) p.volume_kg = Number(kg[1].replace(',','.')) * (kg[2].startsWith('т') ? 1000 : 1);
      const rub = text.match(/(\d[\d\s]*(?:[.,]\d+)?)\s*(тыс\.?|к(?=\s|$))?\s*(?:₽|руб)/);
      if (rub) p.volume_rub = Number(rub[1].replace(/\s/g,'').replace(',','.')) * (rub[2] ? 1000 : 1);
    }
    if (!this.categoriesById[p.category]) p.category = null;
    if (!this.citiesById[p.city]) p.city = null;
    if (!['score','age','complete','name'].includes(p.sort)) p.sort = 'score';
    return p;
  }

  geography(s, city) {
    if (!city) return ['local',''];
    const c = this.citiesById[city], home = (s.home_city || s.city || '').toLowerCase();
    if (c.words.some(w => home.includes(w))) return ['local', `офис или склад: ${s.home_city || s.city}`];
    const area = s.service_area || {}, hay = [area.text || '', ...(area.cities || [])].join(' ').toLowerCase();
    if (c.words.some(w => hay.includes(w))) return ['delivers', `доставляют в ${c.name}`];
    if ((city === 'ekb' ? ['66'] : ['77','50']).includes(s.region_code)) return ['region', `зарегистрированы в регионе: ${c.region}`];
    if (['вся россия','всей россии','по россии','все регионы россии','в любые регионы россии'].some(w => hay.includes(w))) return ['delivers','доставка по России'];
    return ['other','другой регион, доставку нужно уточнить'];
  }

  rate(s, p) {
    const parts = structuredClone(s.parts).filter(x => !['moq','flags'].includes(x.key));
    const cat = this.categoriesById[p.category];
    let points = 20, why = 'категория не задана';
    if (cat) {
      if (s.categories.includes(cat.id)) { points = 25; why = `есть категория "${cat.name}"`; }
      else if (cat.words.some(w => s.products.join(' ').toLowerCase().includes(w))) { points = 15; why = 'категория найдена в списке товаров'; }
      else { points = 0; why = 'категория не подтверждена'; }
    }
    Object.assign(parts.find(x => x.key === 'category'), { points, why });
    const [where, where_why] = this.geography(s,p.city);
    Object.assign(parts.find(x => x.key === 'geo'), { points: { local:20, delivers:15, region:12, other:3 }[where], why:where_why || 'город не задан' });
    // Reliability ages with the calendar, rather than becoming stale after export.
    let reliability = 0; const notes = [];
    if (s.verified_egrul && s.status === 'active') { reliability += 8; notes.push('действующая компания по ЕГРЮЛ'); }
    else if (s.verified_registry) { reliability += 6; notes.push('есть в реестре МСП ФНС'); }
    else notes.push('ИНН не подтверждён');
    if (s.reg_date) {
      const [d,m,y] = s.reg_date.split('.').map(Number), now = new Date();
      const age = (Date.UTC(now.getFullYear(),now.getMonth(),now.getDate()) - Date.UTC(y,m-1,d)) / 86400000 / 365.25;
      reliability += Math.min(8,age*8/5);
      notes.push(age >= 1 ? `на рынке ${roundEven(age)} лет` : 'компания моложе года');
    }
    if (['small','medium'].includes(s.sme)) { reliability += 4; notes.push(s.sme === 'small' ? 'малое предприятие' : 'среднее предприятие'); }
    else if (s.sme === 'micro') { reliability += 2; notes.push('микропредприятие'); }
    Object.assign(parts.find(x => x.key === 'reliability'), { points: Math.round(Math.min(20,reliability)*10)/10, why:notes.join(', ') });
    if (p.volume_kg && s.moq?.kg > p.volume_kg) parts.push({key:'moq',label:'Мин. заказ',points:-15,max:0,why:`минимум ${s.moq.kg} кг больше вашего объёма ${p.volume_kg} кг`});
    if (p.volume_rub && s.moq?.rub > p.volume_rub) parts.push({key:'moq',label:'Мин. заказ',points:-15,max:0,why:`минимум ${s.moq.rub.toLocaleString('ru-RU')} ₽ больше вашего объёма`});
    if (s.red_flags.length) parts.push({key:'flags',label:'Риски',points:-5*Math.min(2,s.red_flags.length),max:0,why:s.red_flags.slice(0,2).join('; ')});
    return {...s, parts, where, where_why, score: Math.max(0,Math.min(100,roundEven(parts.reduce((n,x) => n+x.points,0))))};
  }

  textHits(q) {
    const words = (q.toLowerCase().match(/[\p{L}\p{N}_]{3,}/gu) || []).filter(w => !/^\d+$/.test(w));
    const hits = {};
    for (const word of words) {
      const prefix = word.slice(0, Math.max(4,word.length-2)).normalize('NFD').replace(/\p{M}/gu,'');
      const counts = this.documents.map(d => d.words.filter(w => w.startsWith(prefix)).length);
      const found = counts.filter(Boolean).length;
      const idf = Math.max(1e-6, Math.log((this.documents.length-found+.5)/(found+.5)));
      this.documents.forEach((d,i) => {
        if (counts[i]) hits[d.id] = (hits[d.id] || 0) + idf * counts[i]*2.2/(counts[i]+1.2*(.25+.75*d.words.length/this.averageLength));
      });
    }
    return hits;
  }

  search(query) {
    const p = this.resolve(query), hits = this.textHits(p.q), cat = this.categoriesById[p.category];
    let results = this.suppliers.filter(s => {
      if (cat && !s.categories.includes(cat.id) && !cat.words.some(w => s.products.join(' ').toLowerCase().includes(w))) return false;
      for (const [flag,key] of [['certs','certificates'],['horeca','horeca'],['price','prices'],['verified','verified_egrul']]) if (p[flag] && !has(s[key])) return false;
      return true;
    }).map(s => ({...this.rate(s,p),text_hit:hits[s.id] || 0}));
    if (p.local) results = results.filter(s => s.where !== 'other');
    if (p.q && !p.category && !p.parsed.length) results = results.filter(s => s.text_hit);
    const dateKey = d => d ? d.split('.').reverse().join('') : '99999999';
    results.sort((a,b) => {
      if (p.sort === 'name') return compareText(a.name.toLowerCase(),b.name.toLowerCase());
      if (p.sort === 'age') return compareText(dateKey(a.reg_date),dateKey(b.reg_date)) || compareText(a.name,b.name);
      if (p.sort === 'complete') return b.completeness-a.completeness || b.score-a.score;
      return b.score-a.score || b.text_hit-a.text_hit || compareText(a.name,b.name);
    });
    const registry = this.registry.find(r => r.category === p.category && r.region === this.citiesById[p.city]?.region_code);
    return { params:p, results, total:results.length, registry:registry ? {...registry,region:this.citiesById[p.city].region} : null };
  }

  compare(ids, query) {
    const p = this.resolve(query);
    return [...new Set(ids)].filter(id => this.byId[id]).map(id => this.rate(this.byId[id],p));
  }

  draft(s,p) {
    const cat = this.categoriesById[p.category]?.name.toLowerCase() || s.products.slice(0,3).join(', ') || 'продукции';
    const city = this.citiesById[p.city]?.name || 'нашем городе';
    const asks = [];
    if (!s.prices.length) asks.push('актуальный прайс-лист для HoReCa');
    if (!s.moq) asks.push('минимальную сумму или объём заказа');
    if (!s.delivery) asks.push(`условия и график доставки в ${city}, стоимость доставки`);
    if (!s.certificates.length) asks.push('декларации о соответствии / ветеринарные документы на продукцию');
    asks.push('условия оплаты (отсрочка, безналичный расчёт с НДС)');
    return {subject:`Запрос условий поставки: ${cat}, ${city}`,body:[
      'Здравствуйте!','',`Мы сеть ресторанов доставки в городе ${city}, ищем поставщика: ${cat}.`,
      p.volume_kg ? `Планируемый объём: ${p.volume_kg} кг в неделю.` : 'Объём обсудим после получения условий.','',
      'Пришлите, пожалуйста:',...asks.map(a => '- '+a+';'),'','Если есть возможность, готовы взять пробную поставку.','','Спасибо!',
    ].join('\n')};
  }

  patch(root,s,p) {
    root.querySelectorAll('.score').forEach(el => {
      el.className = 'score' + (s.score < 45 ? ' low' : s.score < 65 ? ' mid' : '');
      el.style.setProperty('--v',s.score); el.setAttribute('aria-label',`Оценка ${s.score} из 100`); el.querySelector('b').textContent = s.score;
    });
    root.querySelectorAll('.why summary, #h-score').forEach(el => el.textContent = `Почему ${s.score} из 100`);
    root.querySelectorAll('.parts').forEach(el => el.innerHTML = s.parts.map(x => `<div class="part ${x.points < 0 ? 'neg' : ''}"><span>${esc(x.label)}</span><span class="bar"><i style="width:${roundEven(Math.abs(x.points)/(x.max || 15)*100)}%"></i></span><span class="pts">${x.points}${x.max ? '/'+x.max : ''}</span><span class="pw">${esc(x.why)}</span></div>`).join(''));
    root.querySelectorAll('[data-geography]').forEach(el => { el.textContent = labels[s.where]; el.className = 'tag '+(['local','delivers'].includes(s.where) ? 'ok' : 'line'); });
    const keep = context(p);
    root.querySelectorAll('a[data-supplier-link]').forEach(el => el.href = appUrl(`/s/${s.id}${keep ? '?'+keep : ''}`));
    const back = root.querySelector('[data-back]'); if (back) back.href = appUrl('/?'+keep);
    const area = root.querySelector('[data-field=area]'); if (area && !s.service_area && s.where_why) area.textContent = s.where_why;
    const subject = root.querySelector('[data-rfq-subject]'), body = root.querySelector('[data-rfq-body]');
    if (subject && body) { const draft = this.draft(s,p); subject.value = draft.subject; body.value = draft.body; }
  }

  searchHtml(query) {
    const res = this.search(query), p = res.params, keep = context(p), tags = [];
    if (p.category) tags.push(['category',this.categoriesById[p.category].name]);
    if (p.city) tags.push(['city',this.citiesById[p.city].name]);
    if (p.volume_kg) tags.push(['volume',`заказ ${p.volume_kg} кг`]);
    for (const [k,label] of [['certs','с документами'],['price','с ценами'],['horeca','HoReCa']]) if (p[k]) tags.push([k,label]);
    const n = res.total, noun = n%10 === 1 && n%100 !== 11 ? 'поставщик' : [2,3,4].includes(n%10) && ![12,13,14].includes(n%100) ? 'поставщика' : 'поставщиков';
    const cards = res.results.map(s => {
      const tpl = document.createElement('template'); tpl.innerHTML = this.fragments[s.id].card;
      this.patch(tpl.content,s,p); return tpl.innerHTML;
    }).join('');
    return `<div class="results-bar" data-context="${esc(keep)}"><h2 data-total="${n}">${n} ${noun}</h2><div class="understood" data-understood>${p.q ? '<span>Понял запрос как:</span>' : ''}${tags.map(([k,v]) => `<span class="tag" data-f="${k}">${esc(v)}</span>`).join('')}</div><label class="sort">Сортировка<select data-sort aria-label="Сортировка">${[['score','по оценке'],['complete','по полноте данных'],['age','старейшие'],['name','по названию']].map(([v,l]) => `<option value="${v}" ${p.sort === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>` +
      (res.registry ? `<p class="registry-note" data-registry>В реестре МСП ФНС в регионе «${esc(res.registry.region)}» по этой категории <b>${res.registry.total.toLocaleString('ru-RU')}</b> компаний (${res.registry.legal.toLocaleString('ru-RU')} юрлиц). Это ориентир для следующего поиска, а не число проверенных поставщиков. Ниже показаны найденные сайты; условия и контакты могут быть неполными.</p>` : '') +
      (cards ? `<div class="list">${cards}</div>` : `<div class="empty" data-empty><h3 style="font-size:20px">Никого не нашли</h3><p class="muted">Попробуйте убрать фильтры или выбрать другой город.</p><a class="btn" href="${appUrl('/?'+(p.category ? 'category='+p.category : ''))}">Сбросить фильтры</a></div>`);
  }

  renderCompare(query) {
    const p = this.resolve(query), ids = new URLSearchParams(query).get('ids')?.split(',') || [];
    const rows = this.compare(ids,query).slice(0,4);
    if (!rows.length) return;
    const table = document.querySelector('[data-compare-table]');
    document.querySelector('[data-empty]')?.remove(); table.closest('.cmp-wrap').hidden = false;
    const header = table.querySelector('thead tr'), body = [...table.querySelectorAll('tbody tr')];
    const bestScore = Math.max(...rows.map(s => s.score)), bestComplete = Math.max(...rows.map(s => s.completeness));
    for (const s of rows) {
      const frag = this.fragments[s.id];
      header.insertAdjacentHTML('beforeend',frag.header);
      body.forEach((row,i) => row.insertAdjacentHTML('beforeend',frag.cells[i]));
      const col = header.lastElementChild;
      this.patch(col,s,p);
      body[0].lastElementChild.classList.toggle('best',rows.length > 1 && s.score === bestScore);
      this.patch(body[0].lastElementChild,s,p);
      const geo = body[1].lastElementChild;
      geo.replaceChildren(document.createTextNode(labels[s.where]));
      if (s.where_why) { const why = document.createElement('span'); why.className = 'muted'; why.textContent = s.where_why; geo.append(document.createElement('br'),why); }
      body[8].lastElementChild.classList.toggle('best',rows.length > 1 && s.completeness === bestComplete);
    }
    const exportLink = document.querySelector('[data-export]');
    exportLink.hidden = false;
    exportLink.addEventListener('click', e => { e.preventDefault(); this.exportCsv(rows); });
    const tags = document.querySelector('[data-compare-context]');
    tags.textContent = [this.categoriesById[p.category]?.name,this.citiesById[p.city]?.name].filter(Boolean).join(' · ');
  }

  exportCsv(rows) {
    const records = [['Поставщик','Юрлицо','ИНН','Город','Сайт','Телефон','Email','Оценка','Мин. заказ','Доставка','Цены','Документы','Следующий шаг'],
      ...rows.map(s => [s.name,s.legal_name,s.inn,s.home_city,s.website,s.phones.map(x => x.value).join(', '),s.emails.map(x => x.value).join(', '),s.score,s.moq?.text,s.delivery?.text,s.prices.map(x => `${x.product}: ${x.price} ₽/${x.unit || ''}`).join('; '),s.certificates.map(x => x.text).join('; '),s.next_action])];
    const cell = value => { let s = String(value ?? ''); if (/^\s*[=+@-]/.test(s)) s = "'"+s; return '"'+s.replaceAll('"','""')+'"'; };
    const url = URL.createObjectURL(new Blob(['\ufeff'+records.map(r => r.map(cell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'suppliers.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  }
}
