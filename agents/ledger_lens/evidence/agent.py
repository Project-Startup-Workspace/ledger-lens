"""Evidence agent: turns one uploaded document into structured ledger entries."""

import logging
from datetime import date
from decimal import Decimal

from ledger_lens.evidence import prompts
from ledger_lens.evidence.schemas import WireExtraction
from ledger_lens.evidence.tools import box_from_gemini, parse_wallet_csv
from ledger_lens.shared.config import Settings
from ledger_lens.shared.llm import Attachment, LlmClient
from ledger_lens.shared.safety import SafetyScreen
from ledger_lens.shared.schemas import (
    Direction,
    EvidenceDocument,
    ExtractionResult,
    LedgerEntry,
)

log = logging.getLogger(__name__)

CSV_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
INJECTION_WARNING = (
    "The page contains text that looks like instructions to the system. "
    "It was ignored; check the original document."
)


class EvidenceAgent:
    """Reads notebooks and statements; never calculates totals."""

    def __init__(self, llm: LlmClient, safety: SafetyScreen, settings: Settings) -> None:
        self._llm = llm
        self._safety = safety
        self._settings = settings

    def read(
        self, doc: EvidenceDocument, data: bytes, *, reference_date: date, currency: str
    ) -> ExtractionResult:
        """Extract every money line from `data`, the bytes of `doc`."""
        if doc.content_type in CSV_TYPES or doc.filename.lower().endswith(".csv"):
            entries, warnings = parse_wallet_csv(data, doc.id)
            return ExtractionResult(
                evidence_id=doc.id,
                kind=doc.kind,
                script="Latin",
                language="und",
                currency=currency,
                entries=entries,
                warnings=warnings,
                model="csv-parser",
            )

        wire = self._llm.generate(
            task=f"extract_{doc.kind.value}",
            model=self._settings.model_extract,
            system=prompts.SYSTEM,
            prompt=prompts.page_prompt(doc.kind.value, reference_date.isoformat(), currency),
            schema=WireExtraction,
            attachments=[Attachment(data, doc.content_type)],
        )
        entries, warnings = self._to_entries(wire, doc.id, reference_date)
        page_text = "\n".join([wire.other_text, *(e.raw_text for e in wire.entries)])
        if self._safety.screen(page_text).flagged:
            log.warning("possible prompt injection in evidence", extra={"evidence_id": doc.id})
            warnings.append(INJECTION_WARNING)
        log.info(
            "evidence read",
            extra={"evidence_id": doc.id, "entries": len(entries), "script": wire.script},
        )
        return ExtractionResult(
            evidence_id=doc.id,
            kind=doc.kind,
            script=wire.script,
            language=wire.language,
            currency=wire.currency or currency,
            entries=entries,
            warnings=[*wire.warnings, *warnings],
            model=f"{self._settings.model_extract}/{prompts.PROMPT_VERSION}",
        )

    @staticmethod
    def _to_entries(
        wire: WireExtraction, evidence_id: str, reference_date: date
    ) -> tuple[list[LedgerEntry], list[str]]:
        """Validate model output line by line; drop what cannot be trusted, and say why."""
        entries: list[LedgerEntry] = []
        warnings: list[str] = []
        for item in wire.entries:
            try:
                day = date.fromisoformat(item.date)
            except ValueError:
                warnings.append(f"Skipped '{item.raw_text}': unreadable date.")
                continue
            if day > reference_date or item.amount < 0:
                warnings.append(f"Skipped '{item.raw_text}': date in the future or negative.")
                continue
            entries.append(
                LedgerEntry(
                    evidence_id=evidence_id,
                    entry_date=day,
                    description=item.description,
                    amount=Decimal(str(item.amount)).quantize(Decimal("0.01")),
                    direction=Direction(item.direction),
                    confidence=min(max(item.confidence, 0.0), 1.0),
                    box=box_from_gemini(item.box_2d),
                    raw_text=item.raw_text,
                )
            )
        return entries, warnings
