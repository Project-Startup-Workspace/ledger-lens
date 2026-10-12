"""Evaluates rule checks against facts. Pure functions: same facts, same result."""

from typing import Any

from ledger_lens.auditpulse.packs import AllOf, Check, FactCheck


def resolve(facts: dict[str, Any], path: str) -> Any:
    """Look up a dotted path such as `disclosure.apr_pct`; missing parts give None."""
    value: Any = facts
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def evaluate(check: Check, facts: dict[str, Any]) -> bool:
    """True when the check passes. A missing fact never passes a check."""
    if isinstance(check, AllOf):
        return all(evaluate(part, facts) for part in check.all)
    return _evaluate_fact(check, resolve(facts, check.fact))


def _evaluate_fact(check: FactCheck, value: Any) -> bool:
    match check.op:
        case "present":
            return value is not None and value != ""
        case "true":
            return value is True
        case "false":
            return value is False
        case "empty":
            return value is not None and len(value) == 0
        case "not_empty":
            return bool(value)
        case "eq":
            return value is not None and bool(value == check.value)
        case "in":
            return value is not None and value in check.value
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    match check.op:
        case "gte":
            return bool(value >= check.value)
        case "lte":
            return bool(value <= check.value)
        case "lt":
            return bool(value < check.value)
    raise ValueError(f"unknown op {check.op}")
