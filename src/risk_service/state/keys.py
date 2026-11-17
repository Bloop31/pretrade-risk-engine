"""Redis key layout.

Every per-account key wraps the account ID in a ``{hash tag}`` so all of an
account's keys land in the same Redis Cluster slot; that is what lets one
``WATCH``/``MULTI`` transaction span them.

==========================================  ======  ==========================================
key                                         type    contents
==========================================  ======  ==========================================
``risk:prices``                             hash    symbol -> last price
``risk:prices:updated_ms``                  hash    symbol -> when that price was written (ms)
``risk:{acct}:positions``                   hash    symbol -> filled signed net position
``risk:{acct}:open``                        hash    ``BUY:<symbol>`` / ``SELL:<symbol>`` -> open qty
``risk:{acct}:order:<client_order_id>``     hash    one accepted, not fully filled order
``risk:{acct}:rate``                        zset    recent order timestamps (ms) for rate limiting
==========================================  ======  ==========================================

All quantities and prices are stored as plain decimal strings.
"""

from risk_service.domain.models import Side

PREFIX = "risk"
PRICES_KEY = f"{PREFIX}:prices"
PRICES_UPDATED_KEY = f"{PREFIX}:prices:updated_ms"


def _account(account: str) -> str:
    return f"{PREFIX}:{{{account}}}"


def positions_key(account: str) -> str:
    return f"{_account(account)}:positions"


def open_orders_key(account: str) -> str:
    return f"{_account(account)}:open"


def open_field(side: Side, symbol: str) -> str:
    return f"{side.value}:{symbol}"


def order_key(account: str, client_order_id: str) -> str:
    return f"{_account(account)}:order:{client_order_id}"


def rate_key(account: str) -> str:
    return f"{_account(account)}:rate"
