# Pre-Trade Risk Check Service

Every order is checked against configurable risk limits **before** it is sent to
the exchange. The service answers `ACCEPT` or `REJECT`, with a result for every
check, in a few milliseconds. Limits live in [`config/rules.yaml`](config/rules.yaml),
which business users can edit without touching code; edits are hot-reloaded
without a restart.

```
 OMS ──► POST /v1/orders/check ──► ACCEPT ──► exchange
                                └► REJECT (with reasons)
 fills / cancels ──► POST /v1/orders/{account}/{id}/fills | /cancel
 market data     ──► PUT  /v1/prices/{symbol}
```

## Contents

- [Quick start](#quick-start)
- [The checks](#the-checks)
- [API](#api)
- [Changing limits](#changing-limits)
- [How it works](#how-it-works)
- [Operating it](#operating-it)
- [Development](#development)

## Quick start

With Docker:

```bash
make up                      # api on :8000 + redis:7
curl localhost:8000/health/ready
make loadtest                # 5000 checks, prints latency percentiles
make down
```

Without Docker (needs a Redis on `REDIS_URL`, default `redis://localhost:6379/0`):

```bash
make install                 # uv sync --locked
make run                     # http://127.0.0.1:8000/docs for the OpenAPI UI
```

Configuration is by environment variable; see [`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Where positions, reservations, prices and rate counters live |
| `RULES_PATH` | `config/rules.yaml` | The rules file |
| `RULES_WATCH_ENABLED` | `true` | Hot-reload the rules file when it changes |
| `RULES_RELOAD_INTERVAL_SECONDS` | `1.0` | How often to look for changes |
| `ADMIN_API_KEY` | *(unset)* | Enables `/admin/*`; callers send it as `X-Admin-Key` |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Logging |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | `0.25` | Redis timeout; on timeout the order is rejected |

## The checks

Every check runs on every order, so a rejection lists *all* the reasons at once.
Limits are inclusive: an order exactly at a limit is accepted.

| Check | Rejects when | Notes |
|---|---|---|
| `trading_enabled` | trading is halted globally or for the account | kill switch |
| `restricted_symbol` | the symbol is on a restricted list | global and per account |
| `order_rate` | the account sent more than `max_orders_per_second` in the last second | counts every attempt, accepted or not |
| `max_order_quantity` | quantity > limit | fat-finger guard |
| `max_order_notional` | quantity × price > limit | MARKET orders use the reference price |
| `price_collar` | a LIMIT price is more than `price_collar_pct` % from the reference price | skipped for MARKET orders |
| `max_position` | the position after the order would exceed the limit | orders that move towards flat always pass |
| `max_gross_exposure` | the account's gross exposure after the order would exceed the limit | orders that reduce exposure always pass |

Positions and exposure count **open orders as well as fills**, on a worst-case
basis: open buys and open sells are tracked separately and never netted, since
there is no guarantee both sides will fill.

## API

Interactive docs at `/docs`. All prices and quantities are **strings**
(`"187.25"`), or integers. JSON numbers with a fraction are rejected with 422,
because by the time they are parsed they have already been rounded through a
binary float.

### Check an order

```bash
curl -X POST localhost:8000/v1/orders/check -H 'content-type: application/json' -d '{
  "client_order_id": "ord-0001", "account": "ACC-1", "symbol": "AAPL",
  "side": "BUY", "order_type": "LIMIT", "quantity": "100", "price": "187.25"
}'
```

```json
{
  "client_order_id": "ord-0001",
  "account": "ACC-1",
  "symbol": "AAPL",
  "decision": "REJECT",
  "rules_version": "3f9c2a1b7d0e",
  "checks": [
    {"check": "trading_enabled",    "status": "PASS", "reason": null, "limit": null,      "value": null},
    {"check": "restricted_symbol",  "status": "PASS", "reason": null, "limit": null,      "value": null},
    {"check": "order_rate",         "status": "PASS", "reason": null, "limit": "50",      "value": "1"},
    {"check": "max_order_quantity", "status": "PASS", "reason": null, "limit": "10000",   "value": "100"},
    {"check": "max_order_notional", "status": "PASS", "reason": null, "limit": "1000000", "value": "18725.00"},
    {"check": "price_collar",       "status": "FAIL",
     "reason": "price 187.25 is 7.0000% from the reference price 175, outside the 5% collar",
     "limit": "5", "value": "7.0000"},
    {"check": "max_position",       "status": "PASS", "reason": null, "limit": "50000",   "value": "100"},
    {"check": "max_gross_exposure", "status": "PASS", "reason": null, "limit": "10000000","value": "18725.00"}
  ]
}
```

A REJECT is a successful check, so it is **HTTP 200**. On ACCEPT the order's
quantity is reserved against the account's limits until it is filled or
cancelled. `rules_version` identifies exactly which rules file made the decision.

### Endpoints

| Method | Path | |
|---|---|---|
| `POST` | `/v1/orders/check` | Check an order (reserves on ACCEPT) |
| `GET` | `/v1/orders/{account}/{client_order_id}` | An open order |
| `POST` | `/v1/orders/{account}/{client_order_id}/fills` | `{"quantity": "40"}`: record an execution |
| `POST` | `/v1/orders/{account}/{client_order_id}/cancel` | Release the unfilled remainder |
| `GET` | `/v1/positions/{account}` | Positions, open orders and gross exposure |
| `PUT` | `/v1/positions/{account}/{symbol}` | `{"quantity": "-200"}`: load a position (e.g. start of day) |
| `GET` | `/v1/prices`, `/v1/prices/{symbol}` | Reference prices |
| `PUT` | `/v1/prices/{symbol}` | `{"price": "187.25"}` |
| `GET` | `/admin/rules` | Rules in force (and a rejected file's problems, if any) |
| `POST` | `/admin/rules/reload` | Reload now |
| `GET` | `/admin/rules/limits?account=&symbol=` | The exact limits an order would get |
| `GET` | `/health/live`, `/health/ready`, `/metrics` | Probes and Prometheus |

Errors share one shape, `{"error": "<code>", "detail": ...}`:

| Status | `error` | When |
|---|---|---|
| 404 | `unknown_order` | fill or cancel for an order that is not open |
| 409 | `duplicate_order` | `client_order_id` already open for the account |
| 409 | `overfill` | fill larger than the order's remaining quantity |
| 422 | *(validation)* / `invalid_rules` | bad request body; rules file rejected on reload |
| 503 | `state_unavailable` | Redis unreachable (non-check endpoints) |

## Changing limits

See **[docs/RULES.md](docs/RULES.md)**, written for the people who own the limits.
In short: edit `config/rules.yaml`, save, and the change applies within about
two seconds. A file with a mistake is never applied; the service keeps the last
good rules and shows what is wrong at `GET /admin/rules`.

## How it works

```
src/risk_service/
  main.py          app factory; lifespan loads rules, opens Redis, starts the watcher
  container.py     the objects built at startup
  settings.py      environment config
  api/             HTTP routers, schemas, error mapping, admin auth
  services/        PreTradeService: rules + state + engine for one order
  domain/          pure logic, no I/O: models, the eight checks, engine, exposure
  rules/           YAML schema and loader, RulesStore (atomic swap), RulesWatcher
  state/           Redis stores: prices, positions and reservations, rate limiter
  observability/   structlog setup, Prometheus metrics, request-ID middleware
```

**Decimal everywhere.** Money and quantities are `Decimal` end to end: parsed
from strings in JSON, stored as strings in Redis, and read from YAML text
without passing through a float. A test fails if `float` appears anywhere in
`domain/` or `rules/`.

**Pure checks.** Each check is a function of an immutable snapshot (order,
limits, reference price, position, exposure, rate count). They are trivial to
test exhaustively at their boundaries and cannot do I/O.

**Atomic check-and-reserve.** The decision and the reservation commit in one
Redis `WATCH`/`MULTI` transaction over the account's keys. If any concurrent
writer touches the account in between, the transaction aborts and the order is
re-decided against fresh state. Two orders can never both squeeze under a limit
only one of them fits. Keys carry an `{account}` hash tag, so this also holds on
Redis Cluster.

**Fail closed.** If Redis is down or slow, a stored value is corrupt, a held
symbol has no price, or a check throws, the order is rejected with a stated
reason. The service refuses to start with an invalid rules file.

**Safe hot reload.** The watcher polls the file and only reads it once it has
stopped changing, so a half-saved file is never read. A new file is fully
validated before it replaces the old one, and each order uses one rules
snapshot from start to finish.

## Operating it

**Health.** `/health/live` means the process is serving; `/health/ready` also
pings Redis (503 when it cannot).

**Metrics** (`/metrics`). No metric is labelled by account or symbol.

| Metric | Use |
|---|---|
| `risk_decisions_total{decision}` | accept/reject rate |
| `risk_check_failures_total{check}` | which limits are biting |
| `risk_check_duration_seconds` | decision latency (buckets from 0.5 ms) |
| `risk_state_errors_total{error}` | orders rejected because Redis was unusable; alert on any |
| `risk_reservation_conflicts_total` | concurrent orders on one account retried |
| `risk_rules_file_valid` | 0 = someone saved a broken rules file; alert on it |
| `risk_rules_reloads_total{trigger,result}` | reload history |
| `risk_rules_info{version}` | rules version in force |

**Logs** are JSON on stdout, one line per event, each tagged with the request's
`x-request-id` (taken from the caller if supplied).

**Scaling.** All state is in Redis, so run as many instances or workers
(`WEB_CONCURRENCY`) as needed. Each instance hot-reloads the rules file itself;
during a reload, instances can disagree for up to about two seconds, and
`rules_version` on each decision records which rules were used.

**Persistence.** The compose file runs Redis with AOF (`appendfsync everysec`),
so reservations and positions survive a restart. Positions here are the
service's working view; reload them from the books of record at start of day
with `PUT /v1/positions/...`.

**Load test.** `make loadtest ARGS="--requests 20000 --concurrency 64 --url http://host:8000"`
prints throughput, p50/p90/p99/p99.9 latency and the decision mix. CI runs it
against the compose stack on every push.

## Development

```bash
make install     # dependencies from uv.lock
make fmt         # ruff fix + format
make check       # lint + mypy --strict + tests: what CI runs
```

Tests use fakeredis by default. Set `REDIS_TEST_URL` to an **empty** Redis
database to also run the concurrency tests against a real server (CI does this
with a `redis:7` service container):

```bash
REDIS_TEST_URL=redis://localhost:6379/15 make test
```

### Windows notes

- Keep the virtualenv out of OneDrive-synced folders:
  `$env:UV_PROJECT_ENVIRONMENT = "$HOME\.venvs\pre-trade"`.
- If Smart App Control blocks the `pytest.exe` / `mypy.exe` launchers, run
  `uv run python -m pytest` and `uv run python -m mypy`. If it blocks the
  uv-downloaded Python, install the signed CPython 3.12 from python.org.
- `make` is not installed by default; the Makefile targets are one-line `uv`
  commands that can be run directly.
