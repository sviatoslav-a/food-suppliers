"""Report coverage and source-link integrity of the bundled snapshot (no network)."""
import json
from collections import Counter
from pathlib import Path

from scout.service import Store


def audit():
    store = Store()
    suppliers = store.all
    invalid = []
    for supplier in suppliers:
        for field in ('phones', 'emails', 'prices', 'certificates', 'moq', 'delivery', 'service_area'):
            values = supplier[field] or []
            for fact in [values] if isinstance(values, dict) else values:
                if fact.get('source') not in supplier['pages']:
                    invalid.append({'supplier': supplier['id'], 'field': field, 'source': fact.get('source')})
    result = {
        'meta': store.meta,
        'suppliers': len(suppliers),
        'with_contacts': sum(bool(s['phones'] or s['emails']) for s in suppliers),
        'coverage': {key: sum(bool(s[key]) for s in suppliers) for key in
                     ('phones', 'emails', 'prices', 'moq', 'delivery', 'certificates', 'verified_egrul', 'verified_registry')},
        'categories': dict(sorted(Counter(c for s in suppliers for c in s['categories']).items())),
        'missing_contacts': [s['website'] for s in suppliers if not (s['phones'] or s['emails'])],
        'invalid_source_links': invalid,
        'limitations': [
            'Source-link membership is checked, not semantic correctness of every extracted claim.',
            'Certificates are website claims, not independently validated certificates.',
            'Registry matching by INN does not prove a website is owned by that entity.',
            'Search uses a fixed snapshot; prices and availability must be reconfirmed.',
        ],
    }
    Path('data/quality_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if invalid:
        raise SystemExit(1)


if __name__ == '__main__':
    audit()
