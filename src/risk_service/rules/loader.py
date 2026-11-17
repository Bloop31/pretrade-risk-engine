"""Load and validate the rules YAML.

The file is edited by hand by non-developers, so the YAML dialect is tightened
against the classic footguns:

* numbers are parsed straight to ``Decimal`` from their text (``0.1`` stays
  exactly ``0.1``; it never passes through a float), and ``.inf``/``.nan`` are
  rejected;
* only ``true``/``false`` are booleans, so tickers like ``ON`` or ``NO`` stay
  strings (YAML 1.1 would read them as booleans);
* duplicate keys are an error instead of last-one-wins.

Every failure is raised as :class:`RulesError` with a list of human-readable
problems, each prefixed with the path of the offending field.
"""

import hashlib
from collections.abc import Hashable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from risk_service.rules.ruleset import RuleSet
from risk_service.rules.schema import RulesDocument


class RulesError(Exception):
    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"invalid rules in {source}: " + "; ".join(problems))


class _RulesYamlLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, Hashable):
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _scalar_text(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    if not isinstance(node, yaml.ScalarNode):
        raise yaml.constructor.ConstructorError(None, None, "expected a scalar", node.start_mark)
    return loader.construct_scalar(node)


def _construct_decimal(loader: yaml.SafeLoader, node: yaml.Node) -> Decimal:
    text = _scalar_text(loader, node)
    try:
        value = Decimal(text.replace("_", ""))
    except InvalidOperation:
        value = Decimal("NaN")
    if not value.is_finite():
        raise yaml.constructor.ConstructorError(
            None, None, f"{text!r} is not a valid finite number", node.start_mark
        )
    return value


def _construct_strict_bool(loader: yaml.SafeLoader, node: yaml.Node) -> bool | str:
    text = _scalar_text(loader, node)
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return text


_RulesYamlLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)
_RulesYamlLoader.add_constructor("tag:yaml.org,2002:bool", _construct_strict_bool)


def parse_rules(content: bytes, *, source: str = "<memory>") -> RuleSet:
    try:
        raw = yaml.load(content, Loader=_RulesYamlLoader)  # noqa: S506 - safe loader subclass
    except yaml.YAMLError as exc:
        raise RulesError(source, [f"YAML syntax error: {exc}"]) from exc

    if not isinstance(raw, dict):
        raise RulesError(source, ["the file must contain a mapping at the top level"])

    try:
        document = RulesDocument.model_validate(raw)
    except ValidationError as exc:
        raise RulesError(source, _format_errors(exc)) from exc

    return RuleSet(
        document=document,
        version=hashlib.sha256(content).hexdigest()[:12],
        source=source,
        loaded_at=datetime.now(UTC),
    )


def load_rules(path: Path) -> RuleSet:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise RulesError(str(path), [f"cannot read file: {exc.strerror or exc}"]) from exc
    return parse_rules(content, source=str(path))


def _format_errors(exc: ValidationError) -> list[str]:
    problems = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        problems.append(f"{location}: {error['msg']}")
    return problems
