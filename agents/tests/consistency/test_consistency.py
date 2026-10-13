"""Notebook-versus-wallet checks, including the planted mismatch in the demo data."""

from datetime import date, timedelta
from decimal import Decimal

from ledger_lens.consistency.agent import ConsistencyAgent
from ledger_lens.consistency.tools import compare, weekly_series
from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.shared.config import Settings
from ledger_lens.shared.llm import build_llm
from ledger_lens.shared.safety import HeuristicScreen
from ledger_lens.shared.schemas import (
    Direction,
    EvidenceDocument,
    EvidenceKind,
    ExtractionResult,
    LedgerEntry,
)
from tests.conftest import DEMO

MONDAY = date(2026, 8, 10)


def daily(*weekly: int, start: date = MONDAY, conf: float = 1.0) -> list[LedgerEntry]:
    """One entry per day, Monday to Sunday, splitting each weekly total evenly."""
    entries = []
    for i, total in enumerate(weekly):
        for d in range(7):
            entries.append(
                LedgerEntry(
                    evidence_id="ev",
                    entry_date=start + timedelta(weeks=i, days=d),
                    description="x",
                    amount=Decimal(total) / 7,
                    direction=Direction.IN,
                    confidence=conf,
                )
            )
    return entries


def run(notebook: list[LedgerEntry], wallet: list[LedgerEntry], tolerance: float = 0.35):
    return compare(weekly_series(notebook, 0.6), weekly_series(wallet, 0.6), tolerance, "LKR")


def test_steady_share_raises_no_flags() -> None:
    report = run(daily(100, 120, 90, 110), daily(40, 48, 36, 44))
    assert report.status == "compared"
    assert (report.flags, report.consistency_score, report.baseline_ratio) == ([], 1.0, 0.4)


def test_inflated_notebook_week_is_flagged_high() -> None:
    [flag] = run(daily(100, 100, 250, 100), daily(40, 40, 40, 40)).flags
    assert flag.week_start == MONDAY + timedelta(weeks=2)
    assert flag.severity == "high"
    assert "receipts" in flag.officer_question


def test_inflation_and_wallet_excess_are_judged_symmetrically() -> None:
    inflated = run(daily(100, 100, 150, 100), daily(40, 40, 40, 40)).flags
    excess = run(daily(100, 100, 100, 100), daily(40, 40, 60, 40)).flags
    assert [f.severity for f in inflated] == [f.severity for f in excess] == ["low"]


def test_material_wallet_money_in_a_blank_notebook_week_is_flagged() -> None:
    notebook = [e for e in daily(100, 100, 100, 100) if e.entry_date.isocalendar().week != 34]
    report = run(notebook, daily(40, 40, 40, 40))
    assert [(f.ratio, f.severity) for f in report.flags] == [(None, "high")]


def test_partial_edge_weeks_are_not_compared() -> None:
    wallet = daily(40, 40, 40, 40, 40)[3:-3]  # starts Thursday, ends Thursday
    report = run(daily(100, 100, 100, 100, 100), wallet)
    assert report.weeks_compared == 3 and report.flags == []


def test_weeks_with_unreadable_notebook_lines_are_skipped_not_flagged() -> None:
    notebook = daily(100, 100, 100, 100)
    notebook[8] = notebook[8].model_copy(update={"confidence": 0.3})
    report = run(notebook, daily(40, 40, 40, 40))
    assert report.weeks_compared == 3 and report.flags == [] and report.notes


def test_too_few_weeks_no_wallet_or_unused_wallet_is_insufficient() -> None:
    assert run(daily(100, 100), daily(40, 40)).status == "insufficient_data"
    assert run(daily(100, 100, 100), []).consistency_score is None
    unused = run(daily(100, 100, 100, 100), daily(0, 0, 0, 500))
    assert unused.status == "insufficient_data" and "rarely used" in unused.notes[-1]


def _read_case(slug: str, currency: str, settings: Settings) -> list[ExtractionResult]:
    agent = EvidenceAgent(build_llm(settings), HeuristicScreen(), settings)
    results = []
    pages = sorted((DEMO / slug).glob("notebook-p*.png"))
    for path in [*pages, DEMO / slug / "wallet-statement.csv"]:
        is_csv = path.suffix == ".csv"
        doc = EvidenceDocument(
            kind=EvidenceKind.WALLET_STATEMENT if is_csv else EvidenceKind.NOTEBOOK,
            filename=path.name,
            content_type="text/csv" if is_csv else "image/png",
            sha256="-",
            blob_key=path.name,
        )
        results.append(
            agent.read(doc, path.read_bytes(), reference_date=date(2026, 10, 12), currency=currency)
        )
    return results


def test_demo_jakarta_case_flags_the_planted_week(settings: Settings) -> None:
    extractions = _read_case("synthetic-warung-jakarta", "IDR", settings)
    report = ConsistencyAgent(settings).check(extractions, "IDR")
    assert [(f.week_start, f.severity) for f in report.flags] == [(date(2026, 9, 14), "high")]


def test_demo_kandy_case_is_consistent(settings: Settings) -> None:
    extractions = _read_case("synthetic-grocer-kandy", "LKR", settings)
    report = ConsistencyAgent(settings).check(extractions, "LKR")
    assert report.status == "compared" and report.flags == []


def test_only_the_most_readable_statement_is_used(settings: Settings) -> None:
    extractions = _read_case("synthetic-grocer-kandy", "LKR", settings)
    wallet = extractions[-1]
    short_copy = wallet.model_copy(update={"evidence_id": "dup", "entries": wallet.entries[:10]})
    report = ConsistencyAgent(settings).check([*extractions, short_copy], "LKR")
    assert report.statement_evidence_id == wallet.evidence_id
    assert report.flags == [] and any("sharing the most readable" in n for n in report.notes)
