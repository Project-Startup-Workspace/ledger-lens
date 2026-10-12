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


def test_exact_matches_are_paired_before_closest(settings: Settings) -> None:
    totals: defaultdict[str, int] = defaultdict(int)
    labels = [
        {"date": "2026-08-10", "amount": 100, "direction": "in"},
        {"date": "2026-08-10", "amount": 110, "direction": "in"},
    ]
    score_page(totals, labels, [entry("2026-08-10", 110), entry("2026-08-10", 140)], settings)
    assert (totals["exact"], totals["wrong_confident"]) == (1, 1)


def test_confident_lines_matching_no_label_count_as_errors(settings: Settings) -> None:
    totals: defaultdict[str, int] = defaultdict(int)
    labels = [{"date": "2026-08-10", "amount": 100, "direction": "in"}]
    invented = [entry("2026-08-10", 100), entry("2026-08-15", 50_000), entry("2026-08-16", 9, 0.3)]
    score_page(totals, labels, invented, settings)
    assert totals["wrong_confident"] == 1  # the low-confidence extra goes to review instead


def test_bias_check_reports_group_rates_and_four_fifths(settings: Settings, tmp_path: Path) -> None:
    model = LogisticModel.load(settings.risk_model_path)
    header = ",".join([*model.features, "group_attr", "defaulted", "is_holdout"])
    strong = "5,0.1,52,10,1,0,0.5"
    weak = "0.2,0.8,2,0,0,0.125,0.95"
    rows = [f"{strong},a,0,true", f"{strong},a,0,true", f"{strong},b,0,true", f"{weak},b,1,true"]
    rows.append(f"{weak},a,1,false")  # a training row: must be ignored
    path = tmp_path / "rows.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    report = bias_check(model, settings.risk_model_path, path)
    assert report.groups["a"]["approval_rate"] == 1.0
    assert report.groups["b"]["approval_rate"] == 0.5
    assert report.four_fifths_ratio == 0.5 and not report.passes_four_fifths
    assert report.rows == "holdout" and report.model_fingerprint


def test_only_a_passing_report_for_this_exact_artifact_counts(
    settings: Settings, tmp_path: Path
) -> None:
    from ledger_lens.shared.governance import (
        artifact_fingerprint,
        bias_report_path,
        has_passing_bias_report,
    )

    artifact = tmp_path / "model.json"
    artifact.write_text(settings.risk_model_path.read_text())
    report = bias_report_path(artifact)
    fingerprint = artifact_fingerprint(artifact)
    report.write_text(f'{{"passes_four_fifths": false, "model_fingerprint": "{fingerprint}"}}')
    assert not has_passing_bias_report(artifact)
    report.write_text(f'{{"passes_four_fifths": true, "model_fingerprint": "{fingerprint}"}}')
    assert has_passing_bias_report(artifact)
    artifact.write_text(artifact.read_text() + " ")  # retrained: report is now stale
    assert not has_passing_bias_report(artifact)
