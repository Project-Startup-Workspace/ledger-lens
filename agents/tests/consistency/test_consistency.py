"""Notebook-versus-wallet checks, including the planted mismatch in the demo data."""

from datetime import date, timedelta
from decimal import Decimal

from ledger_lens.consistency.agent import ConsistencyAgent
from ledger_lens.consistency.tools import compare
from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.shared.config import Settings
from ledger_lens.shared.llm import build_llm
from ledger_lens.shared.safety import HeuristicScreen
from ledger_lens.shared.schemas import EvidenceDocument, EvidenceKind, ExtractionResult
from tests.conftest import DEMO

MONDAY = date(2026, 8, 10)


def weeks(*values: int) -> dict[date, Decimal]:
    return {MONDAY + timedelta(weeks=i): Decimal(v) for i, v in enumerate(values)}


def test_steady_share_raises_no_flags() -> None:
    report = compare(weeks(100, 120, 90, 110), weeks(40, 48, 36, 44), 0.35, "LKR")
    assert report.status == "compared"
    assert report.flags == []
    assert report.consistency_score == 1.0
    assert report.baseline_ratio == 0.4


def test_inflated_notebook_week_is_flagged_high() -> None:
    report = compare(weeks(100, 100, 250, 100), weeks(40, 40, 40, 40), 0.35, "LKR")
    [flag] = report.flags
    assert flag.week_start == MONDAY + timedelta(weeks=2)
    assert flag.severity == "high"
    assert "receipts" in flag.officer_question


def test_wallet_money_in_a_blank_notebook_week_is_flagged() -> None:
    notebook = weeks(100, 100, 100, 100)
    del notebook[MONDAY + timedelta(weeks=1)]
    report = compare(notebook, weeks(40, 40, 40, 40), 0.35, "LKR")
    assert [f.ratio for f in report.flags] == [None]


def test_too_few_weeks_or_no_wallet_is_insufficient() -> None:
    assert compare(weeks(100, 100), weeks(40, 40), 0.35, "LKR").status == "insufficient_data"
    assert compare(weeks(100, 100, 100), {}, 0.35, "LKR").status == "insufficient_data"


def test_only_overlapping_weeks_are_compared() -> None:
    notebook = weeks(100, 100, 100, 100, 100, 100)
    wallet = {k: v for k, v in weeks(0, 0, 40, 40, 40, 40).items() if v}
    report = compare(notebook, wallet, 0.35, "LKR")
    assert report.weeks_compared == 4 and report.flags == []


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
    assert [f.week_start for f in report.flags] == [date(2026, 9, 14)]


def test_demo_kandy_case_is_consistent(settings: Settings) -> None:
    extractions = _read_case("synthetic-grocer-kandy", "LKR", settings)
    report = ConsistencyAgent(settings).check(extractions, "LKR")
    assert report.status == "compared" and report.flags == []
