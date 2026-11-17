"""Prometheus metrics.

Metrics live on the default registry and are defined once at import time.
Route labels use the route template (``/v1/positions/{account}``), never the
raw path, and no metric is labelled by account or symbol, to keep label
cardinality bounded.
"""

from datetime import datetime
from typing import Literal

from prometheus_client import Counter, Gauge, Histogram, Info

# Sub-millisecond resolution: a pre-trade check sits on the order's critical path.
LATENCY_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

# ------------------------------------------------------------------------ HTTP

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

# ------------------------------------------------------------------- decisions

DECISIONS = Counter(
    "risk_decisions",
    "Pre-trade decisions, by outcome.",
    ["decision"],
)

CHECK_FAILURES = Counter(
    "risk_check_failures",
    "Failed risk checks, by check name. One order can fail several checks.",
    ["check"],
)

CHECK_LATENCY = Histogram(
    "risk_check_duration_seconds",
    "End-to-end time to decide one order, including Redis round trips.",
    buckets=LATENCY_BUCKETS,
)

STATE_ERRORS = Counter(
    "risk_state_errors",
    "Orders rejected because risk state could not be read or written.",
    ["error"],
)

RESERVATION_CONFLICTS = Counter(
    "risk_reservation_conflicts",
    "Optimistic transactions retried because a concurrent writer touched the same account.",
)

# ----------------------------------------------------------------------- rules

ReloadTrigger = Literal["admin", "watcher"]
ReloadResultLabel = Literal["changed", "unchanged", "invalid"]

RULES_RELOADS = Counter(
    "risk_rules_reloads",
    "Rules reload attempts, by trigger and result.",
    ["trigger", "result"],
)

RULES_FILE_VALID = Gauge(
    "risk_rules_file_valid",
    "1 if the rules file on disk was valid at the last attempt to load it, else 0. "
    "When 0, the previously loaded rules are still in force.",
)

RULES_LOADED_TIMESTAMP = Gauge(
    "risk_rules_loaded_timestamp_seconds",
    "Unix time at which the rules currently in force were loaded.",
)

RULES_INFO = Info("risk_rules", "The rules currently in force.")


def record_rules_loaded(version: str, source: str, loaded_at: datetime) -> None:
    RULES_INFO.info({"version": version, "source": source})
    RULES_LOADED_TIMESTAMP.set(loaded_at.timestamp())
    RULES_FILE_VALID.set(1)


def record_rules_reload(trigger: ReloadTrigger, result: ReloadResultLabel) -> None:
    RULES_RELOADS.labels(trigger=trigger, result=result).inc()
    RULES_FILE_VALID.set(0 if result == "invalid" else 1)
