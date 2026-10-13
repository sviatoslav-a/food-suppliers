"""Exercise the actual stdio transport, not only the decorated Python functions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio():
    async def check():
        server = StdioServerParameters(command=sys.executable, args=['-m', 'scout.mcp_server'])
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {'search_suppliers', 'get_supplier', 'draft_request'}
                result = await session.call_tool('search_suppliers', {'category': 'dairy', 'city': 'ekb', 'limit': 2})
                assert not result.is_error
                resource = await session.read_resource('scout://taxonomy')
                assert resource.contents
    # Playwright's session fixture owns a loop on the pytest thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(lambda: asyncio.run(asyncio.wait_for(check(), timeout=20))).result(timeout=25)
