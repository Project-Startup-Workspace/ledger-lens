"""Rule-pack models and loading. The JSON format is defined by rule-packs/schema.json."""

import json
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Clause(_Strict):
    id: str
    reference: str
    summary: str


class Source(_Strict):
    id: str
    title: str
    url: str
    clauses: list[Clause]


class FactCheck(_Strict):
    fact: str
    op: Literal["present", "true", "false", "empty", "not_empty", "eq", "gte", "lte", "lt", "in"]
    value: Any = None

    @model_validator(mode="after")
    def _value_fits_op(self) -> "FactCheck":
        """Catch malformed rules when the pack loads, not mid-check on a live case."""
        numeric = isinstance(self.value, int | float) and not isinstance(self.value, bool)
        if self.op in {"gte", "lte", "lt"} and not numeric:
            raise ValueError(f"{self.fact}: '{self.op}' needs a numeric value")
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError(f"{self.fact}: 'in' needs a list value")
        if self.op == "eq" and self.value is None:
            raise ValueError(f"{self.fact}: 'eq' needs a value")
        return self


class AllOf(_Strict):
    all: list["Check"] = Field(min_length=1)


Check = FactCheck | AllOf


class Citation(_Strict):
    source: str
    clause: str


class Rule(_Strict):
    id: str
    title: str
    severity: Literal["info", "minor", "major", "critical"]
    stage: Literal["pre_decision", "post_decision"]
    outcomes: list[Literal["approve", "decline", "refer"]] = ["approve", "decline", "refer"]
    check: Check
    on_fail: Literal["fail", "review"]
    pass_detail: str
    fail_detail: str
    cites: list[Citation] = Field(min_length=1)


class RulePack(_Strict):
    jurisdiction: str
    name: str
    version: str
    last_checked: str
    review_status: Literal["draft", "counsel_reviewed"]
    sources: list[Source]
    rules: list[Rule]

    @model_validator(mode="after")
    def _citations_resolve(self) -> "RulePack":
        """Every citation must name a clause that exists in this pack."""
        known = {(s.id, c.id) for s in self.sources for c in s.clauses}
        for rule in self.rules:
            for cite in rule.cites:
                if (cite.source, cite.clause) not in known:
                    raise ValueError(f"{rule.id} cites unknown {cite.source}/{cite.clause}")
        return self

    @cached_property
    def clauses(self) -> dict[tuple[str, str], tuple[Source, Clause]]:
        return {(s.id, c.id): (s, c) for s in self.sources for c in s.clauses}


class RulePackRegistry:
    """All packs in a directory: one per jurisdiction plus the `common` pack."""

    def __init__(self, root: Path) -> None:
        self._packs: dict[str, RulePack] = {}
        for path in sorted(root.glob("*/pack.json")):
            pack = RulePack.model_validate(json.loads(path.read_text(encoding="utf-8")))
            # The folder name must match, so a copied draft cannot shadow the live pack.
            if pack.jurisdiction != path.parent.name:
                raise ValueError(f"{path}: jurisdiction '{pack.jurisdiction}' != folder name")
            self._packs[pack.jurisdiction] = pack
        self.common = self._packs.pop("common", None)

    def get(self, jurisdiction: str) -> RulePack | None:
        return self._packs.get(jurisdiction.lower())

    def jurisdictions(self) -> list[RulePack]:
        return sorted(self._packs.values(), key=lambda p: p.name)
