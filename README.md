# robinhood-mcp-cli

Programmatic CLI for the Robinhood Trading MCP server. It targets the MCP
endpoint used by Robinhood's "trading with your agent" feature — see the
[official Robinhood support article](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
for what agents can do (long equities and options orders, watchlists, market
data, scanner, account and P&L tools).

It wraps every MCP tool behind a schema-driven interface so each one stays
reachable as the server evolves, adds curated subcommands for the common
operations, and never reads another application's credential store.

## Install

Pre-built single-file binaries for Linux/macOS/Windows are attached to each
[GitHub release](https://github.com/cbangera2/robinhood-mcp-cli/releases)
(e.g. `rh-macos-arm64`). Download the one for your platform, make it
executable, and run it directly — no Python required.

Or install from source:

```bash
python -m pip install .
# or for development
python -m pip install -e ".[dev]"
```

Requires Python 3.11+ (source install only).

> The standalone binaries are unsigned, so macOS Gatekeeper / Windows
> SmartScreen may warn the first time you run them. The source build has no
> such caveat.

## Releasing a new version

Push a tag named `vX.Y.Z`; the release workflow builds binaries for Linux x64,
macOS arm64, and Windows x64, then creates a GitHub release with generated
notes:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Run the release workflow locally with `pytest -q` and
`pyinstaller --onefile --name rh --clean rh_entry.py` first.

## Setup (once)

```bash
# Interactive OAuth: opens the browser, then paste the callback URL
rh setup

# Agent-driven setups: the script polls a callback file and writes the
# authorization URL to <file>.url, so a separate process can drive the browser.
rh setup --callback-file /tmp/rh_cb.txt
```

The token is stored in `state/robinhood_token.json` (default) with restrictive
permissions. Or use a static bearer token without writing secrets to shell
history:

```bash
ROBINHOOD_MCP_BEARER_TOKEN=... rh check
```

## Configuration

Global flags, or a JSON config file (`--config`). Start from the checked-in
example and fill in your own account number:

```bash
cp config.example.json config.json   # config.json is gitignored
$EDITOR config.json                  # set account_number from `rh accounts`
```

The config schema:

```json
{
  "endpoint": "https://agent.robinhood.com/mcp/trading",
  "token_file": "state/robinhood_token.json",
  "account_number": "000000000"
}
```

`account_number` is only taken from this config/flag. Tools that require it
(review/place/cancel, positions, portfolio, options) are refused when it is
absent. Pick the account flagged `agentic_allowed=true` (see `rh setup` /
`rh accounts`).

## Usage

### Read-only

```bash
rh tools                          # every tool the server exposes
rh check                          # quote, portfolio, positions for IAG
rh quote IAG AEM                   # quotes (comma-separated also OK)
rh account                         # portfolio/equity summary
rh accounts                        # brokerage accounts + agentic flags
rh positions                       # equity positions
rh orders                          # recent orders
rh orders --symbol IAG --state filled
rh tradability IAG                 # tradability flags
rh fundamentals IAG                # valuation + trading stats
rh historicals IAG --start-time 2026-01-01T00:00:00Z --interval day
rh price-book IAG
rh watchlists                      # list watchlists
rh watchlist-items <list_id>
rh earnings IAG                    # trailing quarters
rh earnings-calendar --days 7
rh pnl --span month                # realized P&L
rh scans                           # saved scans
rh run-scan <scan_id>
rh tax-lots IAG
rh indicators IAG --type rsi --interval day --start-time 2026-01-01T00:00:00Z
rh financials IAG --period quarterly --limit 8
rh indexes --symbols SPX,NDX
rh index-quotes --ids <index_id>
rh realized-pnl --span month --asset-classes equity,option
rh scanner-specs                        # available scanner filters
```

### Options

Option read commands are read-only. `option-review` prints the server's order
checks without placing anything.

```bash
rh option-level                        # options eligibility / upgrade link
rh option-chains --underlying SPY
rh option-instruments --chain-symbol SPY --expiration-dates 2026-09-18 --type call
rh option-quotes --ids <instrument_id>
rh option-historicals --ids <instrument_id> --start-time 2026-01-01T00:00:00Z
rh option-positions --nonzero
rh option-orders --placed-agent user
rh option-watchlist
rh option-review --leg <option_id>,buy,open --quantity 1 --type limit --price 200
```

A single leg is written `option_id,side,position_effect[,ratio_quantity]`; multi-leg
orders pass a JSON array to `--legs` (e.g. `--legs '[{"option_id":"...","side":"buy","position_effect":"open"}]'`).

`option-place` and `option-cancel` prompt for confirmation unless `--yes` is
given. Options require an `account_number` (agentic-allowed).

```bash
rh option-review --leg <option_id>,buy,open --quantity 1 --type limit --price 200
rh option-place --leg <option_id>,buy,open --quantity 1 --type limit --price 200 --yes
rh option-cancel <order_id> --yes
```

### Watchlists

```bash
rh watchlist-popular
rh watchlist-create --name "gold miners" --emoji ⛏️
rh watchlist-update <list_id> --name "renamed"
rh watchlist-add <list_id> --symbols IAG,AEM
rh watchlist-remove <list_id> --symbols IAG
rh watchlist-follow <list_id>
rh watchlist-unfollow <list_id>
```

### Scanner admin

```bash
rh scan-create --preset default --filters '[{"filter_type":"FILTER_TYPE_PRICE","value":10}]' --title "my scan"
rh scan-filters <scan_id> --filters '[...]'
rh scan-config <scan_id> --sorting-column market_cap --sorting-direction desc
```

### Orders (equities)

`place` and `cancel` prompt for confirmation unless `--yes` is given. Orders
require an `account_number` (agentic-allowed).

```bash
rh review IAG --side buy --type market --quantity 1
rh place IAG --side buy --type market --quantity 1 --yes
rh place IAG --side buy --type limit --quantity 1 --limit-price 18.00 --yes
rh cancel <order_id> --yes
```

### Generic access to any tool

Any MCP tool is reachable via `call`, with arguments as JSON or repeated
`--arg key=value` (values are coerced to the schema's declared types):

```bash
rh call get_equity_quotes --args '{"symbols": ["IAG"]}'
rh call get_earnings_calendar --arg start_date=2026-01-01 --arg days=14
rh call search --arg query=apple --arg limit=5
```

## Safety notes

- Read commands never touch your portfolio.
- Order-mutating commands (`place`, `option-place`, `cancel`, `option-cancel`,
  watchlist/scanner writes) require explicit `--yes` confirmation where
  applicable.
- `account_number` is never auto-derived from `get_accounts`; if it is missing
  the command is refused.
- This tool is for programmatic research/operations. It is not investment
  advice.

## Development

```bash
pytest -q
ruff check rh_mcp_cli tests
```