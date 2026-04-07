"""MCP client — connects to the Omni-Track MCP server via SSE and calls tools."""

import os
import json
import logging

from fastmcp import Client

logger = logging.getLogger(__name__)

MCP_SSE_URL = os.environ.get("MCP_BASE_URL", "http://mcp:8000") + "/sse"


def _parse_result(result) -> any:
    """Parse a CallToolResult into a Python object."""
    if result.isError:
        error_text = result.content[0].text if result.content else "Unknown MCP error"
        raise RuntimeError(f"MCP tool error: {error_text}")
    if result.content:
        for block in result.content:
            if hasattr(block, "text"):
                return json.loads(block.text)
    return None


async def call_tool(tool_name: str, arguments: dict | None = None) -> any:
    """Call a single MCP tool (creates a fresh SSE session)."""
    logger.debug("MCP call: %s(%s)", tool_name, arguments)
    async with Client(MCP_SSE_URL) as client:
        result = await client.call_tool(tool_name, arguments or {})
        return _parse_result(result)


async def call_tools_batch(calls: list[tuple[str, dict]]) -> list:
    """Call multiple MCP tools in a single session (avoids repeated handshakes)."""
    results = []
    async with Client(MCP_SSE_URL) as client:
        for tool_name, arguments in calls:
            result = await client.call_tool(tool_name, arguments)
            results.append(_parse_result(result))
    return results


# ── Convenience wrappers ─────────────────────────────────────────────────────


async def list_metric_types() -> list[dict]:
    return await call_tool("list_metric_types")


async def upsert_reading(**kwargs) -> dict:
    return await call_tool("upsert_reading", kwargs)


async def get_readings(**kwargs) -> list[dict]:
    return await call_tool("get_readings", kwargs)


async def get_latest(**kwargs) -> list[dict]:
    return await call_tool("get_latest", kwargs)


async def get_all_latest() -> list[dict]:
    return await call_tool("get_all_latest")


async def log_insight(**kwargs) -> dict:
    return await call_tool("log_insight", kwargs)


async def set_safe_range(**kwargs) -> dict:
    return await call_tool("set_safe_range", kwargs)


async def get_safe_ranges(**kwargs) -> list[dict]:
    return await call_tool("get_safe_ranges", kwargs)
