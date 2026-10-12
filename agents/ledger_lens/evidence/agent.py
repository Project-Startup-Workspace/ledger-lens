"""Evidence agent: turns one uploaded document into structured ledger entries."""

import logging
from datetime import date, timedelta
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

CSV_TYPES = {"text/csv", "application/csv"}
# Twelve months of history plus slack for a notebook started a few weeks earlier.
MAX_HISTORY = timedelta(days=400)
REMOVED = "[removed: suspected instructions]"
INJECTION_WARNING = (
    "The document contains text that looks like instructions to the system. "
    "It was removed; check the original document."
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
            script, language, read_currency, other_text = "Latin", "und", currency, ""
            model = "csv-parser"
        else:
            wire = self._llm.generate(
                task=f"extract_{doc.kind.value}",
                model=self._settings.model_extract,
                system=prompts.SYSTEM,
                prompt=prompts.page_prompt(doc.kind.value, reference_date.isoformat(), currency),
                schema=WireExtraction,
                attachments=[Attachment(data, doc.content_type)],
            )
            entries, warnings = _to_entries(wire, doc.id)
            warnings = [*wire.warnings, *warnings]
            script, language, other_text = wire.script, wire.language, wire.other_text
            read_currency = (wire.currency or currency).upper()
            model = f"{self._settings.model_extract}/{prompts.PROMPT_VERSION}"

        entries, date_warnings = _within_window(entries, reference_date)
        entries, warnings, flagged = self._screen(entries, warnings, other_text)
        if read_currency != currency.upper():
            # Never add amounts in another currency into the case totals.
            warnings.append(
                f"The document appears to be in {read_currency}, not {currency}. "
                "Its amounts were sent to review instead of the totals."
            )
            entries = [e.model_copy(update={"confidence": 0.0}) for e in entries]
        log.info(
            "evidence read",
            extra={"evidence_id": doc.id, "entries": len(entries), "flagged": flagged},
        )
        return ExtractionResult(
            evidence_id=doc.id,
            kind=doc.kind,
            script=script,
            language=language,
            currency=read_currency,
            entries=entries,
            warnings=[*warnings, *date_warnings],
            model=model,
        )

    def _screen(
        self, entries: list[LedgerEntry], warnings: list[str], other_text: str
    ) -> tuple[list[LedgerEntry], list[str], bool]:
        """Remove text that reads like instructions, wherever the model or file put it."""
        flagged = self._safety.screen(other_text).flagged
        clean_entries = []
        for entry in entries:
            if self._safety.screen(f"{entry.description}\n{entry.raw_text}").flagged:
                flagged = True
                entry = entry.model_copy(update={"description": REMOVED, "raw_text": REMOVED})
            clean_entries.append(entry)
        clean_warnings = []
        for warning in warnings:
            if self._safety.screen(warning).flagged:
                flagged = True
            else:
                clean_warnings.append(warning)
        if flagged:
            log.warning("possible prompt injection in evidence")
            clean_warnings.append(INJECTION_WARNING)
        return clean_entries, clean_warnings, flagged


def _to_entries(wire: WireExtraction, evidence_id: str) -> tuple[list[LedgerEntry], list[str]]:
    """Validate model output line by line; drop what cannot be trusted, and say why."""
    entries: list[LedgerEntry] = []
    warnings: list[str] = []
    for item in wire.entries:
        try:
            day = date.fromisoformat(item.date)
        except ValueError:
            warnings.append(f"Skipped '{item.raw_text}': unreadable date.")
            continue
        if item.amount < 0:
            warnings.append(f"Skipped '{item.raw_text}': negative amount.")
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


def _within_window(
    entries: list[LedgerEntry], reference_date: date
) -> tuple[list[LedgerEntry], list[str]]:
    """Keep entries dated in the history window before the case date.

    A wrong year (05/01 read as 2025 instead of 2026) would otherwise pad the cash flow
    with dozens of empty weeks, so out-of-window lines are dropped and reported.
    """
    earliest = reference_date - MAX_HISTORY
    kept = [e for e in entries if earliest <= e.entry_date <= reference_date]
    dropped = len(entries) - len(kept)
    if not dropped:
        return kept, []
    return kept, [
        f"{dropped} line(s) dated outside {earliest:%d %b %Y} to {reference_date:%d %b %Y} "
        "were skipped; check the year on those pages."
    ]
