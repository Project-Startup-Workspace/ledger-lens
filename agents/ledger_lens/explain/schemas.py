"""Wire schema for the borrower explanation Gemini writes."""

from pydantic import BaseModel, Field


class WireExplanation(BaseModel):
    borrower_text: str = Field(description="The explanation, in the requested language.")
