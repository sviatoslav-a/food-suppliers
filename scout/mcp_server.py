"""MCP server: exposes supplier search to any AI agent (Claude, Codex, an ERP assistant).

Run:  uv run python -m scout.mcp_server     (stdio transport)
"""

from mcp.server.mcpserver import MCPServer

from scout import rfq
from scout.service import Params, Store
from scout.taxonomy import CATEGORIES, CITIES

mcp = MCPServer('scout-suppliers')
store = Store()


def brief(s: dict) -> dict:
    return {k: s.get(k) for k in ('id', 'name', 'legal_name', 'inn', 'home_city', 'website', 'score', 'where', 'next_action',
                                  'description')} | {
        'moq': (s.get('moq') or {}).get('text'), 'delivery': (s.get('delivery') or {}).get('text'),
        'contacts': [x['value'] for x in s['emails'] + s['phones']][:3], 'certificates': [c['text'] for c in s['certificates']],
    }


@mcp.tool()
def search_suppliers(query: str = '', category: str = '', city: str = '', volume_kg: float | None = None,
                     with_documents: bool = False, limit: int = 10) -> dict:
    """Find food suppliers for a restaurant. `query` is free text in Russian, e.g.
    "сыры для пиццы в Екатеринбурге с документами". Optional `category`:
    meat, fish, dairy, veg, grocery, asian, drinks, packaging. Optional `city`: ekb, msk.
    Returns suppliers ranked by an explainable 0-100 score with the next action."""
    res = store.search(Params(q=query, category=category or None, city=city or None, volume_kg=volume_kg, certs=with_documents))
    return {'understood': {k: res['params'][k] for k in ('category', 'city', 'volume_kg', 'certs')},
            'total': res['total'], 'registry': res['registry'], 'suppliers': [brief(s) for s in res['results'][:max(1, min(limit, 100))]]}


@mcp.tool()
def get_supplier(supplier_id: str, category: str = '', city: str = '') -> dict:
    """Full supplier card: terms, prices, documents, registry data, score breakdown and sources."""
    s = store.get(supplier_id, Params(category=category or None, city=city or None))
    return s or {'error': f'unknown supplier {supplier_id}'}


@mcp.tool()
def draft_request(supplier_id: str, category: str = '', city: str = '', volume: str = '') -> dict:
    """Email draft asking the supplier for exactly the terms missing from its website."""
    s = store.get(supplier_id)
    return rfq.draft(s, category or None, city or None, volume) if s else {'error': f'unknown supplier {supplier_id}'}


@mcp.resource('scout://taxonomy')
def taxonomy() -> str:
    """Supported categories and cities."""
    return '\n'.join([f'category {c.id}: {c.name}' for c in CATEGORIES] + [f'city {c.id}: {c.name}' for c in CITIES])


if __name__ == '__main__':
    mcp.run()
