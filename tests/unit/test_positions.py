from decimal import Decimal

from risk_service.domain.models import Side
from risk_service.domain.positions import AccountSnapshot, gross_exposure

D = Decimal


def test_empty_snapshot() -> None:
    snap = AccountSnapshot()
    assert snap.position("AAPL") == 0
    assert snap.directional_position("AAPL", Side.BUY) == 0
    assert gross_exposure(snap, {}) == 0


def test_open_orders_count_only_in_their_own_direction() -> None:
    snap = AccountSnapshot(
        positions={"AAPL": D(100)}, open_buys={"AAPL": D(50)}, open_sells={"AAPL": D(300)}
    )
    assert snap.directional_position("AAPL", Side.BUY) == D(150)
    assert snap.directional_position("AAPL", Side.SELL) == D(-200)
    assert snap.worst_case_quantity("AAPL") == D(200)


def test_gross_exposure_uses_worst_case_per_symbol() -> None:
    snap = AccountSnapshot(
        positions={"AAPL": D(100), "MSFT": D(-10)},
        open_buys={"AAPL": D(50)},
        open_sells={"TSLA": D(5)},
    )
    prices = {"AAPL": D("10.5"), "MSFT": D(400), "TSLA": D(200)}
    # AAPL 150 x 10.5 + MSFT 10 x 400 + TSLA 5 x 200
    assert gross_exposure(snap, prices) == D("1575") + D(4000) + D(1000)


def test_gross_exposure_unknown_when_held_symbol_has_no_price() -> None:
    snap = AccountSnapshot(positions={"AAPL": D(100), "MSFT": D(1)})
    assert gross_exposure(snap, {"AAPL": D(10)}) is None


def test_flat_symbols_need_no_price() -> None:
    snap = AccountSnapshot(positions={"AAPL": D(0)})
    assert gross_exposure(snap, {}) == 0


def test_symbols_union() -> None:
    snap = AccountSnapshot(positions={"A": D(1)}, open_buys={"B": D(1)}, open_sells={"C": D(1)})
    assert snap.symbols() == {"A", "B", "C"}
