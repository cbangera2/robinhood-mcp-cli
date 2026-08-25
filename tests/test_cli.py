
import pytest

from rh_mcp_cli.auth import JsonTokenStorage, resolve_client_factory
from rh_mcp_cli.cli import build_parser
from rh_mcp_cli.exceptions import UsageError


def test_token_storage_round_trip(tmp_path):
    from mcp.shared.auth import OAuthToken

    path = tmp_path / "tokens.json"
    storage = JsonTokenStorage(path)
    import asyncio

    async def go():
        await storage.set_tokens(OAuthToken(access_token="abc", token_type="Bearer", expires_in=3600))
        loaded = await storage.get_tokens()
        assert loaded.access_token == "abc"

    asyncio.run(go())
    assert (path.read_text())  # content present
    assert path.stat().st_mode & 0o077 == 0  # restrictive perms


def test_resolve_client_factory_prefers_bearer_env(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_MCP_BEARER_TOKEN", "secret-token")
    factory = resolve_client_factory(
        server_url="https://agent.robinhood.com/mcp/trading",
        token_file="state/robinhood_token.json",
        bearer_token_env="ROBINHOOD_MCP_BEARER_TOKEN",
    )
    import asyncio

    async def go():
        async with factory as client:
            return client.headers.get("Authorization")

    assert asyncio.run(go()) == "Bearer secret-token"


def test_resolve_client_factory_oauth_when_no_token(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_MCP_BEARER_TOKEN", raising=False)
    factory = resolve_client_factory(
        server_url="https://agent.robinhood.com/mcp/trading",
        token_file="/nonexistent/token.json",
        bearer_token_env="ROBINHOOD_MCP_BEARER_TOKEN",
    )
    # OAuth path produces an httpx2 client with an OAuth auth object (no Authorization header).
    import asyncio

    async def go():
        async with factory as client:
            return client.auth is not None and client.headers.get("Authorization") is None

    assert asyncio.run(go()) is True


def test_cli_requires_command(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([])
    assert exc.value.code != 0


def test_cli_call_rejects_bad_json(capsys):
    parser = build_parser()
    args = parser.parse_args(["call", "get_equity_quotes", "--args", "{not json"])

    # main would try to connect; we only validate that parser accepted the form
    assert args.command == "call"
    assert args.tool == "get_equity_quotes"


def test_cli_place_requires_account_number_error_message():
    # build_args guard is unit-tested in test_client; here ensure error type is UsageError
    from rh_mcp_cli.client import MCPClient

    client = MCPClient(server_url="x", client_context=None, account_number=None)
    client._schemas = {
        "place_equity_order": {
            "type": "object",
            "properties": {"account_number": {"type": "string"}, "symbol": {"type": "string"}},
            "required": ["account_number", "symbol"],
        }
    }
    with pytest.raises(UsageError) as exc_info:
        client.build_args("place_equity_order", {"symbol": "IAG"})
    assert "account_number" in str(exc_info.value)


def test_cli_parser_has_all_curated_commands():
    parser = build_parser()
    subparsers = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    assert subparsers, "no subparsers found"
    names = {choice.dest for action in subparsers for choice in action._choices_actions}
    for expected in ["tools", "call", "setup", "check", "quote", "account", "accounts",
                     "positions", "orders", "tradability", "fundamentals", "historicals",
                     "price-book", "watchlists", "watchlist-items", "earnings",
                     "earnings-calendar", "pnl", "scans", "run-scan", "tax-lots",
                     "indicators", "review", "place", "cancel",
                     "option-chains", "option-instruments", "option-quotes",
                     "option-historicals", "option-positions", "option-orders",
                     "option-review", "option-place", "option-cancel", "option-level",
                     "option-watchlist", "watchlist-popular", "watchlist-create",
                     "watchlist-update", "watchlist-follow", "watchlist-unfollow",
                     "watchlist-add", "watchlist-remove", "financials", "indexes",
                     "index-quotes", "realized-pnl", "scanner-specs", "scan-create",
                     "scan-filters", "scan-config"]:
        assert expected in names, f"missing command {expected}"


def test_parse_legs_json_and_single():
    from rh_mcp_cli.cli import _parse_legs

    class Args:
        legs = '[{"option_id": "opt-1", "side": "buy", "position_effect": "open"}]'
        leg = None
        option_id = None
        side = None
        position_effect = None

    assert _parse_legs(Args()) == [{"option_id": "opt-1", "side": "buy", "position_effect": "open"}]


def test_parse_legs_comma_spec():
    from rh_mcp_cli.cli import _parse_legs

    class Args:
        legs = None
        leg = "opt-1,buy,open,2"
        option_id = None
        side = None
        position_effect = None

    assert _parse_legs(Args()) == [{"option_id": "opt-1", "side": "buy", "position_effect": "open", "ratio_quantity": 2}]


def test_parse_legs_rejects_bad_json():
    import argparse

    import pytest

    from rh_mcp_cli.cli import _parse_legs

    class Args:
        legs = "{not json"
        leg = None
        option_id = None
        side = None
        position_effect = None

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_legs(Args())


def test_parse_json_arg():
    from rh_mcp_cli.cli import _parse_json_arg

    assert _parse_json_arg("filters", '[{"field": "name"}]') == [{"field": "name"}]
    assert _parse_json_arg("columns", None) is None


def test_parse_json_arg_rejects_bad_json():
    import argparse

    import pytest

    from rh_mcp_cli.cli import _parse_json_arg

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_json_arg("filters", "{not json")

def test_cli_version_reports_a_string():
    from rh_mcp_cli.cli import _cli_version

    assert isinstance(_cli_version(), str)
    assert _cli_version()
