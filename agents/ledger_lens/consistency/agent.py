"""Consistency agent: cross-checks notebook figures against an independent statement."""

import logging

from ledger_lens.consistency.tools import (
    WeeklySeries,
    comparable_weeks,
    compare,
    weekly_series,
)
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import ConsistencyReport, EvidenceKind, ExtractionResult

log = logging.getLogger(__name__)

INDEPENDENT_KINDS = {EvidenceKind.WALLET_STATEMENT, EvidenceKind.BANK_STATEMENT}


class ConsistencyAgent:
    """Deterministic: no model call, so every flag can be reproduced exactly."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self, extractions: list[ExtractionResult], currency: str) -> ConsistencyReport:
        """Compare all notebook pages in the case with its best single statement.

        Only one statement is used: summing several would double count transfers between
        accounts and duplicate uploads. The one sharing the most readable weeks with the
        notebook wins.
        """
        min_conf = self._settings.min_extraction_confidence
        same_currency = [x for x in extractions if x.currency.upper() == currency.upper()]
        notes = []
        if len(same_currency) < len(extractions):
            notes.append("Documents in another currency were left out of the comparison.")

        notebook = weekly_series(
            (e for x in same_currency if x.kind is EvidenceKind.NOTEBOOK for e in x.entries),
            min_conf,
        )
        statements = [
            (x.evidence_id, weekly_series(x.entries, min_conf))
            for x in same_currency
            if x.kind in INDEPENDENT_KINDS and x.entries
        ]
        if not statements:
            report = compare(notebook, weekly_series([], min_conf), self._tolerance, currency)
        else:
            statement_id, wallet = max(
                statements, key=lambda s: _comparable_overlap(s[1], notebook)
            )
            if len(statements) > 1:
                notes.append(
                    "Several statements were uploaded; the one sharing the most readable "
                    "weeks with the notebook was compared."
                )
            report = compare(notebook, wallet, self._tolerance, currency, statement_id)
        report = report.model_copy(update={"notes": [*notes, *report.notes]})
        log.info("consistency checked", extra={"status": report.status, "flags": len(report.flags)})
        return report

    @property
    def _tolerance(self) -> float:
        return self._settings.consistency_tolerance


def _comparable_overlap(statement: WeeklySeries, notebook: WeeklySeries) -> int:
    """Weeks this statement and the notebook can actually be compared on.

    The same rule compare() applies (both fully cover the week, nothing unreadable), so
    a long statement for another period, or one that cannot be read, ranks last.
    """
    weeks, _ = comparable_weeks(notebook, statement)
    return len(weeks)
