"""Unit tests for argument coercion and schema-driven client behavior."""

from __future__ import annotations

import pytest

from rh_mcp_cli.client import MCPClient, _coerce, _declared_type
from rh_mcp_cli.exceptions import UsageError


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


SCHEMAS = {
    "get_equity_quotes": {
        "type": "object",
        "properties": {
            "symbols": {"type": ["null", "array"], "items": {"type": "string"}}
        },
        "required": ["symbols"],
        "additionalProperties": False,
    },
    "get_equity_positions": {
        "type": "object",
        "properties": {
            "account_number": {"type": "string"},
            "cursor": {"type": "string"},
        },
        "required": ["account_number"],
        "additionalProperties": False,
    },
    "review_equity_order": {
        "type": "object",
        "properties": {
            "account_number": {"type": "string"},
            "symbol": {"type": "string"},
            "side": {"type": "string"},
            "quantity": {"type": "string"},
            "limit_price": {"type": "string"},
        },
        "required": ["account_number", "symbol", "side"],
        "additionalProperties": False,
    },
    "get_earnings_calendar": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string"},
            "days": {"type": "integer"},
        },
        "additionalProperties": False,
    },
}


def _client(account_number=None) -> MCPClient:
    client = MCPClient(
        server_url="http://unused",
        client_context=None,
        account_number=account_number,
    )
    client._schemas = SCHEMAS
    return client


def test_declared_type_with_null_union():
    assert _declared_type({"type": ["null", "array"]}) == "array"
    assert _declared_type({"type": "string"}) == "string"


def test_coerce_array_from_comma_string():
    assert _coerce({"type": "array", "items": {"type": "string"}}, "IAG,AEM") == ["IAG", "AEM"]
    assert _coerce({"type": ["null", "array"], "items": {"type": "string"}}, "IAG") == ["IAG"]
    assert _coerce({"type": "array", "items": {"type": "string"}}, ["IAG", "AEM"]) == ["IAG", "AEM"]


def test_coerce_scalars():
    assert _coerce({"type": "integer"}, "14") == 14
    assert _coerce({"type": "integer"}, 14) == 14
    assert _coerce({"type": "number"}, "1.5") == 1.5
    assert _coerce({"type": "boolean"}, "yes") is True
    assert _coerce({"type": "boolean"}, "no") is False
    assert _coerce({"type": "string"}, "buy") == "buy"


def test_build_args_filters_unknown_keys():
    client = _client()
    args = client.build_args("get_equity_quotes", {"symbols": ["IAG"], "nope": 1})
    assert args == {"symbols": ["IAG"]}


def test_build_args_injects_account_number_when_required():
    client = _client(account_number="000000000")
    args = client.build_args("get_equity_positions", {})
    assert args == {"account_number": "000000000"}


def test_build_args_missing_account_number_raises():
    client = _client()
    with pytest.raises(UsageError):
        client.build_args("get_equity_positions", {})


def test_build_args_missing_required_field_raises():
    client = _client(account_number="000000000")
    with pytest.raises(UsageError):
        client.build_args("review_equity_order", {"symbol": "IAG"})
    ok = client.build_args(
        "review_equity_order",
        {"symbol": "IAG", "side": "buy", "quantity": "1", "nope": True},
    )
    assert ok == {
        "account_number": "000000000",
        "symbol": "IAG",
        "side": "buy",
        "quantity": "1",
    }


def test_build_args_coerces_integer_property():
    client = _client()
    args = client.build_args("get_earnings_calendar", {"start_date": "2026-01-01", "days": "14"})
    assert args == {"start_date": "2026-01-01", "days": 14}


def test_list_tools_sorted():
    import asyncio

    client = _client()
    assert asyncio.run(client.list_tools()) == sorted(SCHEMAS)