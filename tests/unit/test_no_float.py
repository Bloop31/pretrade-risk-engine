"""Guard rail: money code must never touch ``float``.

Scans the domain and rules packages for any use of the ``float`` name
(annotations, ``float(...)`` calls, ``isinstance(x, float)``) and for float
literals. A line can opt out with a ``# float-ok`` comment explaining why.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "src" / "risk_service"
MONEY_PACKAGES = ("domain", "rules")
FILES = sorted(p for pkg in MONEY_PACKAGES for p in (SRC / pkg).rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_float_in_money_code(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    allowed = {i for i, line in enumerate(source.splitlines(), start=1) if "# float-ok" in line}
    offences = [
        f"line {node.lineno}"
        for node in ast.walk(ast.parse(source))
        if (
            (isinstance(node, ast.Name) and node.id == "float")
            or (isinstance(node, ast.Constant) and isinstance(node.value, float))
        )
        and node.lineno not in allowed
    ]
    assert not offences, f"float used in {path.name}: {offences}"


def test_scan_finds_files() -> None:
    assert len(FILES) > 5
