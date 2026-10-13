import { config } from './config.js';

export const isStatic = config.mode === 'static';
const base = config.basePath.replace(/\/?$/, '/');
export function appUrl(path = '/') {
  const url = new URL(path, 'https://scout.invalid');
  let pathname = url.pathname;
  if (isStatic && pathname !== '/' && !pathname.split('/').pop().includes('.')) pathname = pathname.replace(/\/?$/, '/');
  return base + pathname.slice(1) + url.search + url.hash;
}

let staticSource;
export async function source() {
  if (!staticSource) staticSource = import('./static-source.js').then(async ({ StaticSource }) => {
    const response = await fetch(appUrl('/static/dataset.json'));
    if (!response.ok) throw new Error('Не удалось загрузить базу поставщиков. Попробуйте обновить страницу.');
    return new StaticSource(await response.json());
  });
  return staticSource;
}

export async function searchHtml(query, signal) {
  if (isStatic) return (await source()).searchHtml(query);
  const response = await fetch(appUrl('/?' + query), { headers: { 'x-partial': 'results' }, signal });
  if (!response.ok) throw new Error('Search failed');
  return response.text();
}

export async function suppliers(ids, query) {
  if (isStatic) return (await source()).compare(ids, query);
  const response = await fetch(appUrl(`/api/suppliers?ids=${ids.join(',')}&${query}`));
  if (!response.ok) throw new Error('Не удалось загрузить поставщиков');
  return response.json();
}
