"""Request-for-quote email draft: asks exactly for what we do not know yet."""

from scout.taxonomy import BY_ID, CITY_BY_ID


def draft(s: dict, category: str | None, city: str | None, volume: str = '', company: str = '') -> dict:
    cat = BY_ID[category].name.lower() if category in BY_ID else ', '.join(s['products'][:3]) or 'продукции'
    where = CITY_BY_ID[city].name if city in CITY_BY_ID else 'нашем городе'
    asks = []
    if not s.get('prices'):
        asks.append('актуальный прайс-лист для HoReCa')
    if not s.get('moq'):
        asks.append('минимальную сумму или объём заказа')
    if not s.get('delivery'):
        asks.append(f'условия и график доставки в {where}, стоимость доставки')
    if not s['certificates']:
        asks.append('декларации о соответствии / ветеринарные документы на продукцию')
    asks.append('условия оплаты (отсрочка, безналичный расчёт с НДС)')
    lines = [
        'Здравствуйте!',
        '',
        f'Мы {company or "сеть ресторанов доставки"} в городе {where}, ищем поставщика: {cat}.',
        f'Планируемый объём: {volume}.' if volume else 'Объём обсудим после получения условий.',
        '',
        'Пришлите, пожалуйста:',
        *[f'- {a};' for a in asks],
        '',
        'Если есть возможность, готовы взять пробную поставку.',
        '',
        'Спасибо!',
    ]
    to = s['emails'][0]['value'] if s['emails'] else ''
    return {'to': to, 'subject': f'Запрос условий поставки: {cat}, {where}', 'body': '\n'.join(lines)}
