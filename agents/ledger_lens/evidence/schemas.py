"""Wire schemas: the exact JSON shape Gemini is asked to return for a page.

Kept deliberately flat and simple (strings, numbers, lists) because response schemas
support only a subset of JSON Schema. `agent.py` converts these into shared contracts.
"""

from typing import Literal

from pydantic import BaseModel, Field


class WireEntry(BaseModel):
    date: str = Field(description="Entry date as YYYY-MM-DD.")
    description: str = Field(description="What the line says, in the original language.")
    amount: float = Field(description="The amount as a plain number, no separators.")
    direction: Literal["in", "out"] = Field(description="in = sale or receipt, out = expense.")
    confidence: float = Field(description="0 to 1: how sure the reading of this line is.")
    box_2d: list[int] = Field(
        description="Box around the amount as [ymin, xmin, ymax, xmax], scaled 0-1000."
    )
    raw_text: str = Field(description="The line exactly as written.")


class WireExtraction(BaseModel):
    script: str = Field(description="Writing system, e.g. Latin, Sinhala, Tamil.")
    language: str = Field(description="BCP-47 language code, e.g. id, si, ta, vi.")
    currency: str = Field(description="ISO 4217 code inferred from the page or the hint.")
    entries: list[WireEntry]
    other_text: str = Field(description="Any text on the page that is not a ledger line.")
    warnings: list[str] = Field(description="Problems such as torn, blurred or crossed-out lines.")
