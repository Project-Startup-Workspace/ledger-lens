"""Evaluation scoring and the fairness check."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger_lens.evaluation import bias_check, score_page
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.config import Settings
from ledger_lens.shared.schemas import Direction, LedgerEntry


def entry(day: str, amount: int, confidence: float = 0.9) -> LedgerEntry:
    return LedgerEntry(
        evidence_id="ev",
        entry_date=date.fromisoformat(day),
        description="x",
        amount=Decimal(amount),
        direction=Direction.IN,
        confidence=confidence,
    )


def test_score_page_counts_found_exact_and_confidently_wrong(settings: Settings) -> None:
    totals: defaultdict[str, int] = defaultdict(int)
    labels = [
        {"date": "2026-08-10", "amount": 100, "direction": "in"},
        {"date": "2026-08-11", "amount": 200, "direction": "in"},
        {"date": "2026-08-12", "amount": 300, "direction": "in"},
        {"date": "2026-08-13", "amount": 400, "direction": "in"},
    ]
    entries = [
        entry("2026-08-10", 100),
        entry("2026-08-11", 210),  # wrong and confident
        entry("2026-08-12", 310, confidence=0.4),  # wrong but sent to review
    ]
    score_page(totals, labels, entries, settings)
    assert (totals["labels"], totals["found"], totals["exact"]) == (4, 3, 1)
    assert (totals["wrong_confident"], totals["low"]) == (1, 1)


def test_bias_check_reports_group_rates_and_four_fifths(settings: Settings, tmp_path: Path) -> None:
    model = LogisticModel.load(settings.risk_model_path)
    header = ",".join([*model.features, "group_attr", "defaulted"])
    strong = "5,0.1,52,10,1,0,0.5"
    weak = "0.2,0.8,2,0,0,0.125,0.95"
    rows = [f"{strong},a,0", f"{strong},a,0", f"{strong},b,0", f"{weak},b,1"]
    path = tmp_path / "rows.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    report = bias_check(model, path)
    assert report.groups["a"]["approval_rate"] == 1.0
    assert report.groups["b"]["approval_rate"] == 0.5
    assert report.four_fifths_ratio == 0.5 and not report.passes_four_fifths
