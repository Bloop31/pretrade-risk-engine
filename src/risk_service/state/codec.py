"""Decimal <-> Redis string encoding. Values never pass through a float."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from risk_service.state.errors import CorruptStateError

ZERO = Decimal(0)


def encode(value: Decimal) -> str:
    return format(value, "f")


def decode(raw: str | None, *, key: str = "?") -> Decimal:
    """Parse a stored value; a missing value is zero."""
    if raw is None:
        return ZERO
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise CorruptStateError(f"{key}: {raw!r} is not a decimal") from exc
    if not value.is_finite():
        raise CorruptStateError(f"{key}: {raw!r} is not finite")
    return value


def decode_hash(raw: dict[str, str], *, key: str) -> dict[str, Decimal]:
    return {name: decode(value, key=f"{key}[{name}]") for name, value in raw.items()}


# redis-py types every reply as ``bytes | str`` because the client may or may not
# decode responses. These normalise to ``str`` so the rest of the code is typed.


def text(raw: bytes | str | None) -> str | None:
    return raw.decode() if isinstance(raw, bytes) else raw


def text_hash(raw: Mapping[bytes | str, bytes | str]) -> dict[str, str]:
    return {str(text(k)): str(text(v)) for k, v in raw.items()}
