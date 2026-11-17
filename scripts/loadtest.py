"""Load test for a running risk service.

Fires order checks from many concurrent clients and reports latency
percentiles, throughput and the decision mix. Accepted orders are cancelled
straight away (unless ``--no-cancel``) so reservations do not pile up and the
service is measured in a steady state.

    uv run python scripts/loadtest.py --url http://localhost:8000 --requests 20000 --concurrency 64

Orders are spread over ``--accounts`` accounts so the per-account rate limit
(``max_orders_per_second`` in config/rules.yaml) is not the only thing measured.
"""

import argparse
import asyncio
import itertools
import random
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

import httpx

SYMBOLS = ("AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "NFLX", "AMD")


@dataclass
class Stats:
    latencies_ms: list[float] = field(default_factory=list)
    decisions: Counter[str] = field(default_factory=Counter)
    failed_checks: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=5000, help="order checks to send")
    parser.add_argument("--concurrency", type=int, default=32, help="in-flight requests")
    parser.add_argument("--accounts", type=int, default=50, help="distinct accounts to spread over")
    parser.add_argument("--no-cancel", action="store_true", help="leave accepted orders open")
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


async def _seed_prices(client: httpx.AsyncClient) -> None:
    for i, symbol in enumerate(SYMBOLS):
        response = await client.put(f"/v1/prices/{symbol}", json={"price": f"{100 + 10 * i}"})
        response.raise_for_status()


def _order(rng: random.Random, accounts: int) -> dict[str, str]:
    index = rng.randrange(len(SYMBOLS))
    reference = 100 + 10 * index
    # Mostly in-collar limit prices, a few outside to exercise rejections.
    price = reference * (1 + rng.uniform(-0.06, 0.06))
    return {
        "client_order_id": uuid.uuid4().hex[:24],
        "account": f"LOAD-{rng.randrange(accounts):04d}",
        "symbol": SYMBOLS[index],
        "side": rng.choice(("BUY", "SELL")),
        "order_type": "LIMIT",
        "quantity": str(rng.randint(1, 500)),
        "price": f"{price:.2f}",  # sent as a string, as the API requires
    }


async def _worker(
    client: httpx.AsyncClient,
    orders: "asyncio.Queue[dict[str, str]]",
    stats: Stats,
    cancel: bool,
) -> None:
    while True:
        try:
            order = orders.get_nowait()
        except asyncio.QueueEmpty:
            return
        start = time.perf_counter()
        try:
            response = await client.post("/v1/orders/check", json=order)
        except httpx.HTTPError as exc:
            stats.errors[type(exc).__name__] += 1
            continue
        stats.latencies_ms.append((time.perf_counter() - start) * 1000)

        if response.status_code != 200:
            stats.errors[f"HTTP {response.status_code}"] += 1
            continue
        body = response.json()
        stats.decisions[body["decision"]] += 1
        for check in body["checks"]:
            if check["status"] == "FAIL":
                stats.failed_checks[check["check"]] += 1
        if cancel and body["decision"] == "ACCEPT":
            await client.post(f"/v1/orders/{order['account']}/{order['client_order_id']}/cancel")


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(pct / 100 * (len(sorted_values) - 1)))
    return sorted_values[index]


def _report(stats: Stats, elapsed: float, args: argparse.Namespace) -> None:
    latencies = sorted(stats.latencies_ms)
    done = len(latencies)
    print(f"\nTarget        {args.url}")
    print(f"Requests      {done} ok, {sum(stats.errors.values())} errors")
    print(f"Concurrency   {args.concurrency} over {args.accounts} accounts")
    print(f"Elapsed       {elapsed:.2f} s")
    print(f"Throughput    {done / elapsed:,.0f} checks/s")
    if latencies:
        print(
            "\nLatency (ms)  " + "  ".join(f"{h:>7}" for h in ("p50", "p90", "p99", "p99.9", "max"))
        )
        values = [_percentile(latencies, p) for p in (50, 90, 99, 99.9)] + [latencies[-1]]
        print("              " + "  ".join(f"{v:7.2f}" for v in values))
        print(f"              mean {statistics.fmean(latencies):.2f}")
    print("\nDecisions     " + ", ".join(f"{k} {v}" for k, v in stats.decisions.most_common()))
    if stats.failed_checks:
        print(
            "Failed checks " + ", ".join(f"{k} {v}" for k, v in stats.failed_checks.most_common())
        )
    if stats.errors:
        print("Errors        " + ", ".join(f"{k} {v}" for k, v in stats.errors.most_common()))


async def main() -> int:
    args = _parse_args()
    rng = random.Random(args.seed)
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    async with httpx.AsyncClient(base_url=args.url, limits=limits, timeout=10) as client:
        (await client.get("/health/ready")).raise_for_status()
        await _seed_prices(client)

        orders: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        for order in itertools.islice(
            iter(lambda: _order(rng, args.accounts), None), args.requests
        ):
            orders.put_nowait(order)

        stats = Stats()
        start = time.perf_counter()
        await asyncio.gather(
            *(_worker(client, orders, stats, not args.no_cancel) for _ in range(args.concurrency))
        )
        _report(stats, time.perf_counter() - start, args)
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
