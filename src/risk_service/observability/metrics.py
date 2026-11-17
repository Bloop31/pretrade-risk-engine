"""Prometheus metrics.

Metrics live on the default registry and are defined once at import time.
Route labels use the route template (``/v1/positions/{account}``), never the
raw path, to keep label cardinality bounded.
"""

from prometheus_client import Counter, Histogram

# Sub-millisecond resolution: a pre-trade check sits on the order's critical path.
LATENCY_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

HTTP_REQUESTS = Counter(
    "risk_http_requests",
    "HTTP requests handled, by route and status code.",
    ["method", "route", "status"],
)

HTTP_LATENCY = Histogram(
    "risk_http_request_duration_seconds",
    "HTTP request latency, by route.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
