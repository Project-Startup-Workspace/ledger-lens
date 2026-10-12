"""Cash-flow arithmetic and parsing: every rule and calculation has a test."""

from datetime import date
from decimal import Decimal

from ledger_lens.evidence.tools import box_from_gemini, parse_wallet_csv, weekly_cash_flow
from ledger_lens.shared.schemas import Direction, LedgerEntry


def entry(day: str, amount: str, direction: Direction = Direction.IN, conf: float = 0.9):
    return LedgerEntry(
        evidence_id="ev",
        entry_date=date.fromisoformat(day),
        description="x",
        amount=Decimal(amount),
        direction=direction,
        confidence=conf,
    )


def test_weekly_totals_group_by_iso_week_and_net_out_expenses() -> None:
    summary = weekly_cash_flow(
        [
            entry("2026-08-10", "100"),  # Monday
            entry("2026-08-16", "50"),  # Sunday, same week
            entry("2026-08-12", "30", Direction.OUT),
            entry("2026-08-17", "200"),  # next Monday
        ],
        "LKR",
        0.6,
    )
    first, second = summary.weeks
    assert (first.iso_week, first.sales, first.expenses, first.net) == (
        "2026-W33",
        Decimal(150),
        Decimal(30),
        Decimal(120),
    )
    assert second.sales == Decimal(200)
    assert summary.total_sales == Decimal(350)
    assert summary.avg_weekly_sales == Decimal("175.00")


def test_gap_weeks_count_as_zero_sales() -> None:
    summary = weekly_cash_flow([entry("2026-08-10", "100"), entry("2026-08-24", "100")], "LKR", 0)
    assert [w.sales for w in summary.weeks] == [Decimal(100), Decimal(0), Decimal(100)]
    assert summary.weeks_covered == 3


def test_low_confidence_entries_go_to_review_not_totals() -> None:
    smudged = entry("2026-08-10", "999", conf=0.4)
    summary = weekly_cash_flow([entry("2026-08-10", "100"), smudged], "LKR", 0.6)
    assert summary.total_sales == Decimal(100)
    assert summary.entries_for_review == [smudged]


def test_volatility_is_coefficient_of_variation() -> None:
    summary = weekly_cash_flow([entry("2026-08-10", "100"), entry("2026-08-17", "300")], "LKR", 0)
    assert summary.sales_volatility == 0.5  # stdev 100 / mean 200


def test_empty_input_gives_empty_summary() -> None:
    summary = weekly_cash_flow([], "LKR", 0.6)
    assert (summary.weeks_covered, summary.sales_volatility) == (0, 0.0)


def test_box_from_gemini_reorders_and_scales() -> None:
    box = box_from_gemini([100, 200, 150, 400])
    assert box is not None
    assert (box.x_min, box.y_min, box.x_max, box.y_max) == (0.2, 0.1, 0.4, 0.15)


def test_box_from_gemini_rejects_degenerate_boxes() -> None:
    assert box_from_gemini([100, 200, 100, 400]) is None
    assert box_from_gemini([1, 2, 3]) is None


def test_parse_wallet_csv_reads_directions_and_signed_amounts() -> None:
    data = b"date,description,amount,direction\n2026-08-10,QR,1000,in\n2026-08-11,Supplier,-400,\n"
    entries, warnings = parse_wallet_csv(data, "ev")
    assert [(e.amount, e.direction) for e in entries] == [
        (Decimal(1000), Direction.IN),
        (Decimal(400), Direction.OUT),
    ]
    assert warnings == []


def test_parse_wallet_csv_reports_unreadable_rows() -> None:
    data = b"date,amount,direction\nnot-a-date,10,in\n2026-08-10,10,sideways\n"
    entries, warnings = parse_wallet_csv(data, "ev")
    assert entries == []
    assert len(warnings) == 2


def test_parse_wallet_csv_requires_core_columns() -> None:
    entries, warnings = parse_wallet_csv(b"when,how much\n", "ev")
    assert entries == [] and warnings


def test_parse_wallet_csv_skips_ragged_rows() -> None:
    data = b"date,description,amount,direction\n2026-08-10,QR,1000\n2026-08-10,QR,5,in,extra\n"
    entries, warnings = parse_wallet_csv(data, "ev")
    assert entries == [] and len(warnings) == 2


def test_parse_wallet_csv_rejects_non_numbers_and_sign_conflicts() -> None:
    data = b"date,amount,direction\n2026-08-10,NaN,in\n2026-08-10,Infinity,\n2026-08-11,-500,in\n"
    entries, warnings = parse_wallet_csv(data, "ev")
    assert entries == [] and len(warnings) == 3


def test_parse_wallet_csv_reports_non_utf8_files() -> None:
    entries, warnings = parse_wallet_csv(
        "date,amount\n2026-08-10,5 caf\xe9\n".encode("cp1252"), "ev"
    )
    assert entries == [] and "UTF-8" in warnings[0]
