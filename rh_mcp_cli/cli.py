"""Programmatic CLI for the Robinhood Trading MCP server.

Curated subcommands cover the common read/order operations; `rh call <tool>`
reaches any other MCP tool with schema-typed arguments. Every tool is listed
by `rh tools` and remains reachable even without a curated subcommand.

Order-mutating commands (place/cancel) require --yes confirmation by default.
account_number is only ever taken from the config/flag the operator supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .auth import resolve_client_factory
from .client import MCPClient
from .exceptions import Cancelled, RhError, UsageError

__all__ = ["main"]


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise UsageError(f"config file not found: {path}")
    return json.loads(path.read_text())


def _confirm(prompt: str, *, yes: bool) -> None:
    if yes:
        return
    answer = input(f"{prompt} [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        raise Cancelled("declined")


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


# --------------------------------------------------------------------------
# Curated command handlers. Each receives (client, args, config).
# --------------------------------------------------------------------------


async def cmd_tools(client: MCPClient, args, config) -> None:
    _print({"tools": await client.list_tools()})


async def cmd_call(client: MCPClient, args, config) -> None:
    if args.args:
        values = json.loads(args.args)
    elif args.arg:
        values = {}
        for item in args.arg:
            key, _, value = item.partition("=")
            values[key.strip()] = value
    else:
        values = {}
    if not isinstance(values, dict):
        raise UsageError("--args must be a JSON object")
    result = await client.call(args.tool, client.build_args(args.tool, values))
    _print(result)


async def cmd_setup(client: MCPClient, args, config) -> None:
    tools = await client.list_tools()
    summary: dict[str, Any] = {"token_file": str(client_token_file(args, config)), "tools": tools}
    try:
        accounts = await client.call("get_accounts", client.build_args("get_accounts", {}))
        summary["accounts"] = accounts
        agentic = _find_agentic(accounts)
        if agentic:
            summary["agentic_account"] = agentic
            configured = config.get("account_number") or args.account
            if configured and str(configured) != str(agentic):
                summary["warning"] = (
                    f"configured account {configured} != agentic account {agentic}"
                )
    except RhError as exc:
        summary["accounts"] = f"unavailable: {exc}"
    _print(summary)


async def cmd_check(client: MCPClient, args, config) -> None:
    summary: dict[str, Any] = {
        "token_file": str(client_token_file(args, config)),
        "symbol": args.symbol,
    }
    try:
        quote = await client.call(
            "get_equity_quotes", client.build_args("get_equity_quotes", {"symbols": [args.symbol]})
        )
        summary["quote"] = quote
    except RhError as exc:
        summary["quote"] = f"unavailable: {exc}"
    try:
        account = await client.call("get_portfolio", client.build_args("get_portfolio", {}))
        summary["portfolio"] = account
    except RhError as exc:
        summary["portfolio"] = f"unavailable: {exc}"
    try:
        positions = await client.call(
            "get_equity_positions", client.build_args("get_equity_positions", {})
        )
        summary["positions"] = positions
    except RhError as exc:
        summary["positions"] = f"unavailable: {exc}"
    _print(summary)


async def cmd_quote(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_quotes", client.build_args("get_equity_quotes", {"symbols": args.symbols})
    )
    _print(result)


async def cmd_account(client: MCPClient, args, config) -> None:
    result = await client.call("get_portfolio", client.build_args("get_portfolio", {}))
    _print(result)


async def cmd_accounts(client: MCPClient, args, config) -> None:
    result = await client.call("get_accounts", client.build_args("get_accounts", {}))
    _print(result)


async def cmd_positions(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_positions", client.build_args("get_equity_positions", {})
    )
    _print(result)


async def cmd_orders(client: MCPClient, args, config) -> None:
    values = _pick(args, {"symbol": "symbol", "state": "state", "order_id": "order_id",
                          "created_at_gte": "created_at_gte", "placed_agent": "placed_agent"})
    result = await client.call(
        "get_equity_orders", client.build_args("get_equity_orders", values)
    )
    _print(result)


async def cmd_tradability(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_tradability",
        client.build_args("get_equity_tradability", {"symbols": args.symbols}),
    )
    _print(result)


async def cmd_fundamentals(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_fundamentals",
        client.build_args("get_equity_fundamentals", {"symbols": args.symbols}),
    )
    _print(result)


async def cmd_historicals(client: MCPClient, args, config) -> None:
    values = {
        "symbols": args.symbols,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "interval": args.interval,
        "bounds": args.bounds,
        "adjustment_type": args.adjustment_type,
    }
    result = await client.call(
        "get_equity_historicals", client.build_args("get_equity_historicals", values)
    )
    _print(result)


async def cmd_price_book(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_price_book", client.build_args("get_equity_price_book", {"symbols": args.symbols})
    )
    _print(result)


async def cmd_watchlists(client: MCPClient, args, config) -> None:
    result = await client.call("get_watchlists", client.build_args("get_watchlists", {}))
    _print(result)


async def cmd_watchlist_items(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_watchlist_items", client.build_args("get_watchlist_items", {"list_id": args.list_id})
    )
    _print(result)


async def cmd_earnings(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_earnings_results", client.build_args("get_earnings_results", {"symbol": args.symbol})
    )
    _print(result)


async def cmd_earnings_calendar(client: MCPClient, args, config) -> None:
    values = {"start_date": args.start_date, "days": args.days, "filter": args.filter}
    result = await client.call(
        "get_earnings_calendar", client.build_args("get_earnings_calendar", values)
    )
    _print(result)


async def cmd_pnl(client: MCPClient, args, config) -> None:
    values = {"span": args.span, "symbol": args.symbol}
    result = await client.call(
        "get_pnl_trade_history", client.build_args("get_pnl_trade_history", values)
    )
    _print(result)


async def cmd_scans(client: MCPClient, args, config) -> None:
    result = await client.call("get_scans", client.build_args("get_scans", {}))
    _print(result)


async def cmd_run_scan(client: MCPClient, args, config) -> None:
    result = await client.call("run_scan", client.build_args("run_scan", {"scan_id": args.scan_id}))
    _print(result)


async def cmd_tax_lots(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_equity_tax_lots",
        client.build_args("get_equity_tax_lots", {"symbol": args.symbol}),
    )
    _print(result)


async def cmd_indicators(client: MCPClient, args, config) -> None:
    values = {
        "symbol": args.symbol,
        "type": args.type,
        "interval": args.interval,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "bounds": args.bounds,
        "output": args.output,
        "period": args.period,
    }
    result = await client.call(
        "get_equity_technical_indicators", client.build_args("get_equity_technical_indicators", values)
    )
    _print(result)


async def cmd_review(client: MCPClient, args, config) -> None:
    values = _order_values(args)
    result = await client.call("review_equity_order", client.build_args("review_equity_order", values))
    _print(result)


async def cmd_place(client: MCPClient, args, config) -> None:
    values = _order_values(args)
    arguments = client.build_args("place_equity_order", values)
    _confirm(
        f"Place {args.side} {values.get('quantity') or values.get('dollar_amount')} "
        f"{args.symbol} ({values.get('type')}) on account {client.account_number}?",
        yes=args.yes,
    )
    result = await client.call("place_equity_order", arguments)
    _print(result)


async def cmd_cancel(client: MCPClient, args, config) -> None:
    arguments = client.build_args("cancel_equity_order", {"order_id": args.order_id})
    _confirm(f"Cancel order {args.order_id}?", yes=args.yes)
    result = await client.call("cancel_equity_order", arguments)
    _print(result)


# --------------------------------------------------------------------------
# Options.
# --------------------------------------------------------------------------


async def cmd_option_chains(client: MCPClient, args, config) -> None:
    values = {"ids": args.ids, "underlying_symbol": args.underlying}
    result = await client.call("get_option_chains", client.build_args("get_option_chains", values))
    _print(result)


async def cmd_option_instruments(client: MCPClient, args, config) -> None:
    values = {
        "chain_id": args.chain_id,
        "chain_symbol": args.chain_symbol,
        "expiration_dates": args.expiration_dates,
        "strike_price": args.strike_price,
        "type": args.type,
        "state": args.state,
        "tradability": args.tradability,
        "ids": args.ids,
        "cursor": args.cursor,
    }
    result = await client.call(
        "get_option_instruments", client.build_args("get_option_instruments", values)
    )
    _print(result)


async def cmd_option_quotes(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_option_quotes",
        client.build_args("get_option_quotes", {"instrument_ids": args.ids}),
    )
    _print(result)


async def cmd_option_historicals(client: MCPClient, args, config) -> None:
    values = {
        "instrument_ids": args.ids,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "interval": args.interval,
        "bounds": args.bounds,
    }
    result = await client.call(
        "get_option_historicals", client.build_args("get_option_historicals", values)
    )
    _print(result)


async def cmd_option_positions(client: MCPClient, args, config) -> None:
    values = {
        "nonzero": args.nonzero,
        "chain_ids": args.chain_ids,
        "option_ids": args.option_ids,
        "type": args.type,
        "option_type": args.option_type,
        "expiration_date": args.expiration_date,
        "expiration_date_lte": args.expiration_date_lte,
        "expiration_date_gte": args.expiration_date_gte,
        "cursor": args.cursor,
    }
    result = await client.call(
        "get_option_positions", client.build_args("get_option_positions", values)
    )
    _print(result)


async def cmd_option_orders(client: MCPClient, args, config) -> None:
    values = {
        "order_id": args.order_id,
        "state": args.state,
        "created_at_gte": args.created_at_gte,
        "chain_ids": args.chain_ids,
        "underlying_type": args.underlying_type,
        "placed_agent": args.placed_agent,
        "cursor": args.cursor,
    }
    result = await client.call(
        "get_option_orders", client.build_args("get_option_orders", values)
    )
    _print(result)


async def cmd_option_review(client: MCPClient, args, config) -> None:
    values = _option_order_values(args)
    result = await client.call("review_option_order", client.build_args("review_option_order", values))
    _print(result)


async def cmd_option_place(client: MCPClient, args, config) -> None:
    values = _option_order_values(args)
    arguments = client.build_args("place_option_order", values)
    _confirm(
        f"Place option order ({len(arguments.get('legs', []))} legs) for "
        f"{arguments.get('quantity')} contracts on account {client.account_number}?",
        yes=args.yes,
    )
    result = await client.call("place_option_order", arguments)
    _print(result)


async def cmd_option_cancel(client: MCPClient, args, config) -> None:
    arguments = client.build_args("cancel_option_order", {"order_id": args.order_id})
    _confirm(f"Cancel option order {args.order_id}?", yes=args.yes)
    result = await client.call("cancel_option_order", arguments)
    _print(result)


async def cmd_option_level(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_option_level_upgrade_info", client.build_args("get_option_level_upgrade_info", {})
    )
    _print(result)


async def cmd_option_watchlist(client: MCPClient, args, config) -> None:
    result = await client.call("get_option_watchlist", client.build_args("get_option_watchlist", {}))
    _print(result)


# --------------------------------------------------------------------------
# Watchlist mutations and discovery.
# --------------------------------------------------------------------------


async def cmd_watchlist_popular(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_popular_watchlists", client.build_args("get_popular_watchlists", {})
    )
    _print(result)


async def cmd_watchlist_create(client: MCPClient, args, config) -> None:
    values = {
        "display_name": args.name,
        "icon_emoji": args.emoji,
        "display_description": args.description,
    }
    result = await client.call("create_watchlist", client.build_args("create_watchlist", values))
    _print(result)


async def cmd_watchlist_update(client: MCPClient, args, config) -> None:
    values = {
        "list_id": args.list_id,
        "display_name": args.name,
        "icon_emoji": args.emoji,
        "display_description": args.description,
    }
    result = await client.call("update_watchlist", client.build_args("update_watchlist", values))
    _print(result)


async def cmd_watchlist_follow(client: MCPClient, args, config) -> None:
    result = await client.call(
        "follow_watchlist", client.build_args("follow_watchlist", {"list_id": args.list_id})
    )
    _print(result)


async def cmd_watchlist_unfollow(client: MCPClient, args, config) -> None:
    result = await client.call(
        "unfollow_watchlist", client.build_args("unfollow_watchlist", {"list_id": args.list_id})
    )
    _print(result)


async def cmd_watchlist_add(client: MCPClient, args, config) -> None:
    values = {
        "list_id": args.list_id,
        "symbols": args.symbols,
        "currency_pair_ids": args.currency_pairs,
        "index_ids": args.index_ids,
    }
    result = await client.call("add_to_watchlist", client.build_args("add_to_watchlist", values))
    _print(result)


async def cmd_watchlist_remove(client: MCPClient, args, config) -> None:
    values = {
        "list_id": args.list_id,
        "symbols": args.symbols,
        "currency_pair_ids": args.currency_pairs,
        "index_ids": args.index_ids,
    }
    result = await client.call(
        "remove_from_watchlist", client.build_args("remove_from_watchlist", values)
    )
    _print(result)


# --------------------------------------------------------------------------
# Market data additions.
# --------------------------------------------------------------------------


async def cmd_financials(client: MCPClient, args, config) -> None:
    values = {"symbols": args.symbols, "period": args.period, "limit": args.limit}
    result = await client.call("get_financials", client.build_args("get_financials", values))
    _print(result)


async def cmd_indexes(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_indexes", client.build_args("get_indexes", {"symbols": args.symbols})
    )
    _print(result)


async def cmd_index_quotes(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_index_quotes",
        client.build_args("get_index_quotes", {"instrument_ids": args.ids}),
    )
    _print(result)


async def cmd_realized_pnl(client: MCPClient, args, config) -> None:
    values = {
        "span": args.span,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "asset_classes": args.asset_classes,
        "display_currency": args.display_currency,
    }
    result = await client.call(
        "get_realized_pnl", client.build_args("get_realized_pnl", values)
    )
    _print(result)


# --------------------------------------------------------------------------
# Scanner admin.
# --------------------------------------------------------------------------


async def cmd_scanner_specs(client: MCPClient, args, config) -> None:
    result = await client.call(
        "get_scanner_filter_specs", client.build_args("get_scanner_filter_specs", {})
    )
    _print(result)


async def cmd_scan_create(client: MCPClient, args, config) -> None:
    values = {
        "scan_id": args.scan_id,
        "preset": args.preset,
        "filters": _parse_json_arg("filters", args.filters),
        "columns": _parse_json_arg("columns", args.columns),
        "title": args.title,
    }
    result = await client.call("create_scan", client.build_args("create_scan", values))
    _print(result)


async def cmd_scan_filters(client: MCPClient, args, config) -> None:
    values = {"scan_id": args.scan_id, "filters": _parse_json_arg("filters", args.filters)}
    result = await client.call(
        "update_scan_filters", client.build_args("update_scan_filters", values)
    )
    _print(result)


async def cmd_scan_config(client: MCPClient, args, config) -> None:
    values = {
        "scan_id": args.scan_id,
        "sorting_column": args.sorting_column,
        "sorting_direction": args.sorting_direction,
        "columns": _parse_json_arg("columns", args.columns),
    }
    result = await client.call(
        "update_scan_config", client.build_args("update_scan_config", values)
    )
    _print(result)


# --------------------------------------------------------------------------
# Shared helpers for curated handlers.
# --------------------------------------------------------------------------


def _pick(args, mapping: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dest, prop in mapping.items():
        value = getattr(args, dest, None)
        if value is not None:
            out[prop] = value
    return out


def _order_values(args) -> dict[str, Any]:
    return {
        "symbol": args.symbol,
        "side": args.side,
        "type": args.order_type,
        "quantity": args.quantity,
        "dollar_amount": args.dollar_amount,
        "limit_price": args.limit_price,
        "stop_price": args.stop_price,
        "time_in_force": args.time_in_force,
        "market_hours": args.market_hours,
    }


def _option_order_values(args) -> dict[str, Any]:
    return {
        "legs": _parse_legs(args),
        "direction": args.direction,
        "type": args.order_type,
        "quantity": args.quantity,
        "price": args.price,
        "stop_price": args.stop_price,
        "time_in_force": args.time_in_force,
        "market_hours": args.market_hours,
        "chain_symbol": args.chain_symbol,
        "underlying_type": args.underlying_type,
    }


def _parse_legs(args) -> list[dict[str, Any]]:
    if getattr(args, "legs", None):
        try:
            parsed = json.loads(args.legs)
        except json.JSONDecodeError as exc:
            raise argparse.ArgumentTypeError(f"Invalid --legs JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise argparse.ArgumentTypeError("--legs must be a JSON array of leg objects")
        return parsed
    leg = getattr(args, "leg", None)
    if leg:
        return [_parse_leg(leg)]
    return [{"option_id": args.option_id, "side": args.side, "position_effect": args.position_effect}]


def _parse_leg(spec: str) -> dict[str, Any]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) < 3:
        raise argparse.ArgumentTypeError(
            "--leg must be option_id,side,position_effect[,ratio_quantity]"
        )
    leg: dict[str, Any] = {
        "option_id": parts[0],
        "side": parts[1],
        "position_effect": parts[2],
    }
    if len(parts) >= 4 and parts[3]:
        leg["ratio_quantity"] = int(parts[3])
    return leg


def _parse_json_arg(name: str, raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid --{name} JSON: {exc}") from exc


def _find_agentic(accounts: Any) -> str | None:
    if isinstance(accounts, dict):
        accounts = accounts.get("data", {}).get("accounts", accounts.get("accounts", []))
    if isinstance(accounts, list):
        for account in accounts:
            if isinstance(account, dict) and account.get("agentic_allowed"):
                return account.get("account_number") or account.get("rhs_account_number")
    return None


def client_token_file(args, config: dict[str, Any]) -> Path:
    return Path(args.token_file or config.get("token_file", "state/robinhood_token.json"))


# --------------------------------------------------------------------------
# Parser construction.
# --------------------------------------------------------------------------

COMMANDS: dict[str, Any] = {
    "tools": cmd_tools,
    "call": cmd_call,
    "setup": cmd_setup,
    "check": cmd_check,
    "quote": cmd_quote,
    "account": cmd_account,
    "accounts": cmd_accounts,
    "positions": cmd_positions,
    "orders": cmd_orders,
    "tradability": cmd_tradability,
    "fundamentals": cmd_fundamentals,
    "historicals": cmd_historicals,
    "price-book": cmd_price_book,
    "watchlists": cmd_watchlists,
    "watchlist-items": cmd_watchlist_items,
    "earnings": cmd_earnings,
    "earnings-calendar": cmd_earnings_calendar,
    "pnl": cmd_pnl,
    "scans": cmd_scans,
    "run-scan": cmd_run_scan,
    "tax-lots": cmd_tax_lots,
    "indicators": cmd_indicators,
    "review": cmd_review,
    "place": cmd_place,
    "cancel": cmd_cancel,
    "option-chains": cmd_option_chains,
    "option-instruments": cmd_option_instruments,
    "option-quotes": cmd_option_quotes,
    "option-historicals": cmd_option_historicals,
    "option-positions": cmd_option_positions,
    "option-orders": cmd_option_orders,
    "option-review": cmd_option_review,
    "option-place": cmd_option_place,
    "option-cancel": cmd_option_cancel,
    "option-level": cmd_option_level,
    "option-watchlist": cmd_option_watchlist,
    "watchlist-popular": cmd_watchlist_popular,
    "watchlist-create": cmd_watchlist_create,
    "watchlist-update": cmd_watchlist_update,
    "watchlist-follow": cmd_watchlist_follow,
    "watchlist-unfollow": cmd_watchlist_unfollow,
    "watchlist-add": cmd_watchlist_add,
    "watchlist-remove": cmd_watchlist_remove,
    "financials": cmd_financials,
    "indexes": cmd_indexes,
    "index-quotes": cmd_index_quotes,
    "realized-pnl": cmd_realized_pnl,
    "scanner-specs": cmd_scanner_specs,
    "scan-create": cmd_scan_create,
    "scan-filters": cmd_scan_filters,
    "scan-config": cmd_scan_config,
}


def _add_symbols(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("symbols", nargs="+" if required else "*", help="One or more ticker symbols")


def _cli_version() -> str:
    try:
        from rh_mcp_cli._version import __version__

        return str(__version__)
    except ImportError:
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("robinhood-mcp-cli")
    except PackageNotFoundError:
        return "0.0.0.dev0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rh",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=None, help="JSON config file (endpoint, token_file, account_number)")
    parser.add_argument("--token-file", type=Path, default=None, help="Override token file path")
    parser.add_argument("--endpoint", type=str, default=None, help="Override MCP endpoint URL")
    parser.add_argument("--account", type=str, default=None, help="Override account_number")
    parser.add_argument("--callback-file", type=Path, default=None, help="Callback URL poll file (agent-driven setups)")
    parser.add_argument("--bearer-token", type=str, default=None, help="Static bearer token (prefer env ROBINHOOD_MCP_BEARER_TOKEN)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_cli_version()}")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm order-mutating commands")

    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("tools", help="List every available MCP tool")
    p.add_argument("--format", dest="fmt", choices=["json", "lines"], default="json")

    p = sub.add_parser("call", help="Call any MCP tool (generic fallback)")
    p.add_argument("tool", help="Tool name (see `rh tools`)")
    p.add_argument("--args", default=None, help="JSON object of arguments")
    p.add_argument("--arg", action="append", default=None, metavar="KEY=VALUE", help="Single argument (repeatable)")

    p = sub.add_parser("setup", help="Run onboarding OAuth flow and report accounts")
    p = sub.add_parser("check", help="Verify connection, quote, portfolio, positions")
    p.add_argument("--symbol", default="IAG")

    p = sub.add_parser("quote", help="Current quote for one or more symbols")
    _add_symbols(p)

    p = sub.add_parser("account", help="Portfolio/account summary")
    p = sub.add_parser("accounts", help="List brokerage accounts")
    p = sub.add_parser("positions", help="Equity positions")

    p = sub.add_parser("orders", help="List equity orders")
    p.add_argument("--symbol", default=None)
    p.add_argument("--state", default=None)
    p.add_argument("--order-id", dest="order_id", default=None)
    p.add_argument("--created-at-gte", dest="created_at_gte", default=None)
    p.add_argument("--placed-agent", dest="placed_agent", default=None)

    p = sub.add_parser("tradability", help="Tradability for one or more symbols")
    _add_symbols(p)

    p = sub.add_parser("fundamentals", help="Fundamentals for one or more symbols")
    _add_symbols(p)

    p = sub.add_parser("historicals", help="OHLC history")
    _add_symbols(p)
    p.add_argument("--start-time", dest="start_time", required=True, help="RFC3339 UTC, e.g. 2026-01-01T00:00:00Z")
    p.add_argument("--end-time", dest="end_time", default=None)
    p.add_argument("--interval", default=None)
    p.add_argument("--bounds", default=None)
    p.add_argument("--adjustment-type", dest="adjustment_type", default=None)

    p = sub.add_parser("price-book", help="Price book (level-1-ish) for one or more symbols")
    _add_symbols(p)

    p = sub.add_parser("watchlists", help="List watchlists")
    p = sub.add_parser("watchlist-items", help="Items in a watchlist")
    p.add_argument("list_id")

    p = sub.add_parser("earnings", help="Trailing earnings results for one symbol")
    p.add_argument("symbol")
    p = sub.add_parser("earnings-calendar", help="Earnings calendar window")
    p.add_argument("--start-date", dest="start_date", default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--filter", default=None)

    p = sub.add_parser("pnl", help="Realized P&L trade history")
    p.add_argument("--span", default="week", choices=["week", "month", "3month", "ytd", "all"])
    p.add_argument("--symbol", default=None)

    p = sub.add_parser("scans", help="List saved scans")
    p = sub.add_parser("run-scan", help="Run a scan")
    p.add_argument("scan_id")

    p = sub.add_parser("tax-lots", help="Tax lots for a symbol")
    p.add_argument("symbol")

    p = sub.add_parser("indicators", help="Technical indicator series")
    p.add_argument("symbol")
    p.add_argument("--type", required=True)
    p.add_argument("--interval", required=True)
    p.add_argument("--start-time", dest="start_time", required=True)
    p.add_argument("--end-time", dest="end_time", default=None)
    p.add_argument("--bounds", default=None)
    p.add_argument("--output", default=None)
    p.add_argument("--period", type=int, default=None)

    p = sub.add_parser("review", help="Review an order without placing it")
    _add_order_args(p)
    p = sub.add_parser("place", help="Place an equity order (requires --yes)")
    _add_order_args(p)
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    p = sub.add_parser("cancel", help="Cancel an equity order (requires --yes)")
    p.add_argument("order_id")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    # Options.
    p = sub.add_parser("option-chains", help="Option chains for one or more symbols")
    p.add_argument("--ids", default=None, help="Comma-separated chain UUIDs")
    p.add_argument("--underlying", dest="underlying", default=None, help="Underlying symbol, e.g. SPY")
    p = sub.add_parser("option-instruments", help="Option instruments (filterable)")
    p.add_argument("--chain-id", dest="chain_id", default=None)
    p.add_argument("--chain-symbol", dest="chain_symbol", default=None)
    p.add_argument("--expiration-dates", dest="expiration_dates", default=None)
    p.add_argument("--strike-price", dest="strike_price", default=None)
    p.add_argument("--type", default=None, help="call or put")
    p.add_argument("--state", default=None)
    p.add_argument("--tradability", default=None)
    p.add_argument("--ids", default=None, help="Comma-separated instrument UUIDs")
    p.add_argument("--cursor", default=None)
    p = sub.add_parser("option-quotes", help="Quotes for option instruments")
    p.add_argument("--ids", required=True, help="Comma-separated instrument UUIDs")
    p = sub.add_parser("option-historicals", help="Historical prices for option instruments")
    p.add_argument("--ids", required=True, help="Comma-separated instrument UUIDs")
    p.add_argument("--start-time", dest="start_time", required=True)
    p.add_argument("--end-time", dest="end_time", default=None)
    p.add_argument("--interval", default=None)
    p.add_argument("--bounds", default=None)
    p = sub.add_parser("option-positions", help="Option positions")
    p.add_argument("--nonzero", action="store_true")
    p.add_argument("--chain-ids", dest="chain_ids", default=None)
    p.add_argument("--option-ids", dest="option_ids", default=None)
    p.add_argument("--type", default=None, help="long or short")
    p.add_argument("--option-type", dest="option_type", default=None, help="call or put")
    p.add_argument("--expiration-date", dest="expiration_date", default=None)
    p.add_argument("--expiration-date-lte", dest="expiration_date_lte", default=None)
    p.add_argument("--expiration-date-gte", dest="expiration_date_gte", default=None)
    p.add_argument("--cursor", default=None)
    p = sub.add_parser("option-orders", help="Option orders (filterable)")
    p.add_argument("--order-id", dest="order_id", default=None)
    p.add_argument("--state", default=None)
    p.add_argument("--created-at-gte", dest="created_at_gte", default=None)
    p.add_argument("--chain-ids", dest="chain_ids", default=None)
    p.add_argument("--underlying-type", dest="underlying_type", default=None, help="equity or index")
    p.add_argument("--placed-agent", dest="placed_agent", default=None)
    p.add_argument("--cursor", default=None)
    p = sub.add_parser("option-review", help="Review an option order without placing it")
    _add_option_order_args(p)
    p = sub.add_parser("option-place", help="Place an option order (requires --yes)")
    _add_option_order_args(p)
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p = sub.add_parser("option-cancel", help="Cancel an option order (requires --yes)")
    p.add_argument("order_id")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p = sub.add_parser("option-level", help="Option level / upgrade eligibility")
    p = sub.add_parser("option-watchlist", help="Option watchlist contents")

    # Watchlist mutations.
    p = sub.add_parser("watchlist-popular", help="Popular public watchlists")
    p = sub.add_parser("watchlist-create", help="Create a watchlist")
    p.add_argument("--name", dest="name", required=True)
    p.add_argument("--emoji", dest="emoji", default=None)
    p.add_argument("--description", dest="description", default=None)
    p = sub.add_parser("watchlist-update", help="Update a watchlist")
    p.add_argument("list_id")
    p.add_argument("--name", dest="name", default=None)
    p.add_argument("--emoji", dest="emoji", default=None)
    p.add_argument("--description", dest="description", default=None)
    p = sub.add_parser("watchlist-follow", help="Follow a public watchlist")
    p.add_argument("list_id")
    p = sub.add_parser("watchlist-unfollow", help="Unfollow a public watchlist")
    p.add_argument("list_id")
    p = sub.add_parser("watchlist-add", help="Add symbols to a watchlist")
    p.add_argument("list_id")
    p.add_argument("--symbols", default=None)
    p.add_argument("--currency-pairs", dest="currency_pairs", default=None)
    p.add_argument("--index-ids", dest="index_ids", default=None)
    p = sub.add_parser("watchlist-remove", help="Remove symbols from a watchlist")
    p.add_argument("list_id")
    p.add_argument("--symbols", default=None)
    p.add_argument("--currency-pairs", dest="currency_pairs", default=None)
    p.add_argument("--index-ids", dest="index_ids", default=None)

    # Market data additions.
    p = sub.add_parser("financials", help="Reported financials for symbols")
    _add_symbols(p)
    p.add_argument("--period", choices=["quarterly", "annual"], default=None)
    p.add_argument("--limit", type=int, default=None)
    p = sub.add_parser("indexes", help="Index metadata")
    p.add_argument("--symbols", default=None)
    p = sub.add_parser("index-quotes", help="Quotes for index instruments")
    p.add_argument("--ids", required=True, help="Comma-separated index instrument UUIDs")
    p = sub.add_parser("realized-pnl", help="Realized P&L (custom window or span)")
    p.add_argument("--span", choices=["day", "week", "month", "3month", "year", "all"], default=None)
    p.add_argument("--start-date", dest="start_date", default=None)
    p.add_argument("--end-date", dest="end_date", default=None)
    p.add_argument("--asset-classes", dest="asset_classes", default=None)
    p.add_argument("--display-currency", dest="display_currency", default=None)

    # Scanner admin.
    p = sub.add_parser("scanner-specs", help="Available scanner filter specifications")
    p = sub.add_parser("scan-create", help="Create a scan")
    p.add_argument("--scan-id", dest="scan_id", default=None)
    p.add_argument("--preset", default=None)
    p.add_argument("--filters", default=None, help="JSON filters object")
    p.add_argument("--columns", default=None, help="JSON columns object")
    p.add_argument("--title", default=None)
    p = sub.add_parser("scan-filters", help="Update a scan's filters")
    p.add_argument("scan_id")
    p.add_argument("--filters", required=True, help="JSON filters object")
    p = sub.add_parser("scan-config", help="Update a scan's config")
    p.add_argument("scan_id")
    p.add_argument("--sorting-column", dest="sorting_column", default=None)
    p.add_argument("--sorting-direction", dest="sorting_direction", default=None)
    p.add_argument("--columns", default=None, help="JSON columns object")
    return parser


def _add_order_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("symbol")
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--type", dest="order_type", choices=["market", "limit", "stop_market", "stop_limit"], default="market")
    parser.add_argument("--quantity", default=None, help="Shares (fractional OK for market+regular_hours)")
    parser.add_argument("--dollar-amount", dest="dollar_amount", default=None, help="USD notional, market only")
    parser.add_argument("--limit-price", dest="limit_price", default=None)
    parser.add_argument("--stop-price", dest="stop_price", default=None)
    parser.add_argument("--time-in-force", dest="time_in_force", choices=["gfd", "gtc"], default="gfd")
    parser.add_argument("--market-hours", dest="market_hours", choices=["regular_hours", "extended_hours", "all_day_hours"], default="regular_hours")


def _add_option_order_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--leg",
        default=None,
        help="Single leg as option_id,side,position_effect[,ratio_quantity]",
    )
    group.add_argument("--legs", default=None, help="JSON array of leg objects")
    parser.add_argument("--option-id", dest="option_id", default=None, help="option_id for single-leg orders")
    parser.add_argument("--side", choices=["buy", "sell"], default=None, help="side for single-leg orders")
    parser.add_argument("--position-effect", dest="position_effect", choices=["open", "close"], default=None)
    parser.add_argument("--direction", choices=["debit", "credit", "debit_or_credit"], default=None)
    parser.add_argument("--quantity", default=None, help="Contracts")
    parser.add_argument("--type", dest="order_type", choices=["market", "limit", "stop_market", "stop_limit"], default="market")
    parser.add_argument("--price", default=None, help="Limit price (required for limit orders)")
    parser.add_argument("--stop-price", dest="stop_price", default=None)
    parser.add_argument("--time-in-force", dest="time_in_force", choices=["gfd", "gtc"], default="gfd")
    parser.add_argument("--market-hours", dest="market_hours", choices=["regular_hours", "extended_hours", "all_day_hours"], default="regular_hours")
    parser.add_argument("--chain-symbol", dest="chain_symbol", default=None)
    parser.add_argument("--underlying-type", dest="underlying_type", choices=["equity", "index"], default=None)


# --------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    endpoint = (
        args.endpoint
        or config.get("endpoint")
        or "https://agent.robinhood.com/mcp/trading"
    )
    token_file = client_token_file(args, config)
    account_number = args.account or config.get("account_number")
    if args.bearer_token:
        import os

        os.environ["ROBINHOOD_MCP_BEARER_TOKEN"] = args.bearer_token

    factory = resolve_client_factory(
        server_url=endpoint,
        token_file=token_file,
        bearer_token_env="ROBINHOOD_MCP_BEARER_TOKEN",
        callback_file=args.callback_file,
        client_name="robinhood-mcp-cli",
    )
    handler = COMMANDS[args.command]
    async with MCPClient(
        server_url=endpoint,
        client_context=factory,
        account_number=account_number,
    ) as client:
        await handler(client, args, config)


def main(argv: list[str] | None = None) -> int:
    # The Robinhood server returns 400 on session termination; the mcp library
    # logs a warning for that. It is expected, so silence it to keep JSON clean.
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
        return 0
    except Cancelled:
        print("cancelled", file=sys.stderr)
        return 1
    except RhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())