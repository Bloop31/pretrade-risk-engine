from pathlib import Path

from httpx import AsyncClient

from tests.metrics import sample

ORDER = {
    "client_order_id": "ord-1",
    "account": "ACC-1",
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": "10",
    "price": "100",
}


async def test_decision_metrics(client: AsyncClient) -> None:
    await client.put("/v1/prices/AAPL", json={"price": "100"})
    accepts = sample("risk_decisions_total", decision="ACCEPT")
    rejects = sample("risk_decisions_total", decision="REJECT")
    restricted = sample("risk_check_failures_total", check="restricted_symbol")
    observations = sample("risk_check_duration_seconds_count")

    await client.post("/v1/orders/check", json=ORDER)
    await client.post("/v1/orders/check", json={**ORDER, "client_order_id": "o2", "symbol": "XYZ"})

    assert sample("risk_decisions_total", decision="ACCEPT") == accepts + 1
    assert sample("risk_decisions_total", decision="REJECT") == rejects + 1
    assert sample("risk_check_failures_total", check="restricted_symbol") == restricted + 1
    assert sample("risk_check_duration_seconds_count") == observations + 2


async def test_metrics_endpoint_exposes_service_metrics(client: AsyncClient) -> None:
    await client.post("/v1/orders/check", json=ORDER)
    body = (await client.get("/metrics")).text
    for name in (
        "risk_decisions_total",
        "risk_check_duration_seconds_bucket",
        "risk_rules_info{",
        "risk_rules_file_valid",
        "risk_rules_loaded_timestamp_seconds",
    ):
        assert name in body


async def test_rejected_rules_file_is_visible_to_operators(
    client: AsyncClient, admin_headers: dict[str, str], rules_path: Path
) -> None:
    _write(rules_path, "schema_version: 1\n")
    await client.post("/admin/rules/reload", headers=admin_headers)

    body = (await client.get("/admin/rules", headers=admin_headers)).json()

    assert body["rejected_file"]["problems"] == ["defaults: Field required"]
    assert body["document"]["defaults"]["max_position"] == "5000"  # old rules still in force


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
