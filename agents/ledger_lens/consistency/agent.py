"""Consistency agent: cross-checks notebook figures against independent statements."""

import logging

from ledger_lens.consistency.tools import compare, weekly_inflows
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import ConsistencyReport, EvidenceKind, ExtractionResult

log = logging.getLogger(__name__)

INDEPENDENT_KINDS = {EvidenceKind.WALLET_STATEMENT, EvidenceKind.BANK_STATEMENT}


class ConsistencyAgent:
    """Deterministic: no model call, so every flag can be reproduced exactly."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self, extractions: list[ExtractionResult], currency: str) -> ConsistencyReport:
        """Compare all notebook pages with all wallet and bank statements in the case."""
        min_conf = self._settings.min_extraction_confidence
        notebook = weekly_inflows(
            (e for x in extractions if x.kind is EvidenceKind.NOTEBOOK for e in x.entries),
            min_conf,
        )
        wallet = weekly_inflows(
            (e for x in extractions if x.kind in INDEPENDENT_KINDS for e in x.entries),
            min_conf,
        )
        report = compare(notebook, wallet, self._settings.consistency_tolerance, currency)
        log.info(
            "consistency checked",
            extra={"status": report.status, "flags": len(report.flags)},
        )
        return report
