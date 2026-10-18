"""Calendar helpers shared by agents that group entries by week."""

from datetime import date, timedelta


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())
