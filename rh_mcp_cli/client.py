"""Schema-driven client for the Robinhood Trading MCP server.

The client introspects the server's tool schemas at connect time so that every
tool is reachable generically (``call``), and so that argument values can be
coerced to the JSON types each schema declares. ``account_number`` is injected
automatically only where a tool requires it, using the value supplied by the
operator (never looked up on their behalf).
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any, Self

from .exceptions import MCPError, RhError, UsageError


def _parse_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if content:
        for item in content:
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return result


class MCPClient:
    """Thin, schema-aware wrapper around an MCP client session."""

    def __init__(
        self,
        *,
        server_url: str,
        client_context,
        account_number: str | None = None,
    ):
        self.server_url = server_url
        self.client_context = client_context
        self.account_number = account_number
        self._stack: AsyncExitStack | None = None
        self.session = None
        self._schemas: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> Self:
        import mcp
        from mcp.client.streamable_http import streamable_http_client

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        client = await self._stack.enter_async_context(self.client_context)
        streams = await self._stack.enter_async_context(
            streamable_http_client(self.server_url, http_client=client)
        )
        read_stream, write_stream = streams[:2]
        self.session = await self._stack.enter_async_context(
            mcp.ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        listed = await self.session.list_tools()
        self._schemas = {
            tool.name: (
                getattr(tool, "input_schema", None)
                or getattr(tool, "inputSchema", None)
                or {}
            )
            for tool in listed.tools
        }
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._stack is not None:
            try:
                await self._stack.__aexit__(exc_type, exc, traceback)
            except BaseException as teardown_error:  # noqa: BLE001 - context-manager teardown
                if exc is not None:
                    # Preserve the original exception (e.g. Cancelled) rather
                    # than masking it with session-teardown noise.
                    raise exc
                print(
                    f"warning: MCP session teardown failed (ignored): {teardown_error}",
                    flush=True,
                )
        self.session = None
        self._stack = None

    async def list_tools(self) -> list[str]:
        return sorted(self._schemas)

    def schema(self, name: str) -> dict[str, Any]:
        schema = self._schemas.get(name)
        if schema is None:
            raise MCPError(f"tool not found: {name}")
        return schema

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.session is None:
            raise RhError("not connected")
        if name not in self._schemas:
            raise MCPError(f"tool not found: {name}")
        try:
            result = await self.session.call_tool(name, arguments)
        except Exception as exc:  # MCPError, mcp.shared.exceptions.MCPError, etc.
            raise MCPError(f"{name} failed: {exc}") from exc
        return _parse_result(result)

    def build_args(self, tool_name: str, values: dict[str, Any]) -> dict[str, Any]:
        """Coerce provided values to the tool schema's declared types and
        inject account_number where required. Unknown keys are dropped."""
        schema = self.schema(tool_name)
        properties = schema.get("properties", {})
        built: dict[str, Any] = {}
        for key in properties:
            if key not in values or values[key] is None:
                continue
            built[key] = _coerce(properties[key], values[key])
        required = set(schema.get("required", []))
        if "account_number" in required:
            if not self.account_number:
                raise UsageError(
                    f"{tool_name} requires account_number; pass --account or set it in config"
                )
            built["account_number"] = self.account_number
        for missing in sorted(required - set(built)):
            raise UsageError(f"{tool_name} requires argument: {missing}")
        return built


def _coerce(prop: dict[str, Any], value: Any) -> Any:
    """Coerce a raw CLI value to the JSON-schema type declared for a property."""
    ptype = _declared_type(prop)
    if ptype == "array":
        items = _split_items(value)
        item_type = _declared_type(prop.get("items", {}) or {})
        if item_type == "integer":
            return [int(item) for item in items]
        if item_type == "number":
            return [float(item) for item in items]
        return items
    if ptype == "integer":
        return int(value)
    if ptype == "number":
        return float(value)
    if ptype == "boolean":
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    return value


def _declared_type(prop: dict[str, Any]) -> str:
    ptype = prop.get("type", "string")
    if isinstance(ptype, list):
        return next((t for t in ptype if t != "null"), "string")
    return ptype


def _split_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (int, float)):
        return [value]
    return [item.strip() for item in str(value).split(",") if item.strip()]