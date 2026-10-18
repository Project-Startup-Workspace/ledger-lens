"""Deterministic helpers for the evidence agent: parsing and cash-flow arithmetic.

Gemini reads numbers; these functions add them up. Nothing here calls a model.
"""

import csv
import io
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from ledger_lens.shared.dates import week_start
from ledger_lens.shared.schemas import (
    BoundingBox,
    CashFlowSummary,
    Direction,
    LedgerEntry,
    WeekTotal,
)

_IN_WORDS = {"in", "credit", "cr", "received", "+"}
_OUT_WORDS = {"out", "debit", "dr", "paid", "-"}
ZERO = Decimal(0)


def box_from_gemini(box_2d: list[int]) -> BoundingBox | None:
    """Convert Gemini's [ymin, xmin, ymax, xmax] on a 0-1000 scale to page fractions."""
    if len(box_2d) != 4:
        return None
    y_min, x_min, y_max, x_max = (min(max(v, 0), 1000) / 1000 for v in box_2d)
    if x_max <= x_min or y_max <= y_min:
        return None
    return BoundingBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def parse_wallet_csv(data: bytes, evidence_id: str) -> tuple[list[LedgerEntry], list[str]]:
    """Read a wallet or bank export with date, description, amount and direction columns.

    A signed amount without a direction column is also accepted. Rows that cannot be
    read are reported as warnings rather than guessed.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["The file is not a UTF-8 CSV. Export it again as 'CSV UTF-8'."]
    reader = csv.DictReader(io.StringIO(text))
    fields = {name.strip().lower() for name in reader.fieldnames or []}
    if not {"date", "amount"} <= fields:
        return [], ["CSV needs at least 'date' and 'amount' columns."]

    entries: list[LedgerEntry] = []
    warnings: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        # DictReader marks short rows with None values and long rows with a None key.
        if None in raw or None in raw.values():
            warnings.append(f"Row {line_no} skipped: wrong number of columns.")
            continue
        row = {k.strip().lower(): v.strip() for k, v in raw.items()}
        try:
            amount = Decimal(row["amount"].replace(",", ""))
            day = date.fromisoformat(row["date"])
        except (InvalidOperation, ValueError):
            warnings.append(f"Row {line_no} skipped: unreadable date or amount.")
            continue
        if not amount.is_finite():
            warnings.append(f"Row {line_no} skipped: amount is not a number.")
            continue
        word = row.get("direction", "").lower()
        direction = _direction(word, amount)
        if direction is None:
            warnings.append(f"Row {line_no} skipped: unknown direction '{word}'.")
            continue
        if word and amount < 0:
            warnings.append(f"Row {line_no} skipped: negative amount conflicts with '{word}'.")
            continue
        entries.append(
            LedgerEntry(
                evidence_id=evidence_id,
                entry_date=day,
                description=row.get("description", ""),
                amount=abs(amount),
                direction=direction,
                confidence=1.0,
                raw_text=",".join(raw.values()),
            )
        )
    return entries, warnings


def _direction(word: str, amount: Decimal) -> Direction | None:
    if word in _IN_WORDS or (not word and amount >= 0):
        return Direction.IN
    if word in _OUT_WORDS or (not word and amount < 0):
        return Direction.OUT
    return None


def weekly_cash_flow(
    entries: Iterable[LedgerEntry], currency: str, min_confidence: float
) -> CashFlowSummary:
    """Sum sales and expenses per ISO week.

    Entries below `min_confidence` are excluded and returned for officer review rather
    than guessed, so totals never include unread figures.
    """
    accepted: list[LedgerEntry] = []
    for_review: list[LedgerEntry] = []
    for entry in entries:
        (accepted if entry.confidence >= min_confidence else for_review).append(entry)

    sales: dict[date, Decimal] = defaultdict(lambda: ZERO)
    expenses: dict[date, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[date, int] = defaultdict(int)
    for entry in accepted:
        week = week_start(entry.entry_date)
        target = sales if entry.direction is Direction.IN else expenses
        target[week] += entry.amount
        counts[week] += 1

    weeks = _week_range(counts.keys())
    totals = [
        WeekTotal(
            week_start=week,
            iso_week=f"{week.isocalendar().year}-W{week.isocalendar().week:02d}",
            sales=sales[week],
            expenses=expenses[week],
            net=sales[week] - expenses[week],
            entry_count=counts[week],
        )
        for week in weeks
    ]
    weekly_sales = [float(t.sales) for t in totals]
    total_sales = sum((t.sales for t in totals), ZERO)
    total_expenses = sum((t.expenses for t in totals), ZERO)
    n_weeks = len(totals)
    mean_sales = statistics.fmean(weekly_sales) if weekly_sales else 0.0
    return CashFlowSummary(
        currency=currency,
        weeks=totals,
        total_sales=total_sales,
        total_expenses=total_expenses,
        avg_weekly_sales=_per_week(total_sales, n_weeks),
        avg_weekly_net=_per_week(total_sales - total_expenses, n_weeks),
        sales_volatility=statistics.pstdev(weekly_sales) / mean_sales if mean_sales else 0.0,
        weeks_covered=n_weeks,
        entries_for_review=for_review,
    )


def _week_range(weeks: Iterable[date]) -> list[date]:
    """Every week from the first to the last seen.

    A week with no entries inside the range counts as zero sales: a gap in a notebook
    is information the officer and the risk model should see, not something to skip.
    """
    seen = sorted(weeks)
    if not seen:
        return []
    span = (seen[-1] - seen[0]).days // 7
    return [seen[0] + timedelta(weeks=i) for i in range(span + 1)]


def _per_week(amount: Decimal, weeks: int) -> Decimal:
    return (amount / weeks).quantize(Decimal("0.01")) if weeks else ZERO
