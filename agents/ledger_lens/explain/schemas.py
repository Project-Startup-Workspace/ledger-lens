"""Wire schema for the borrower explanation Gemini writes."""

from pydantic import BaseModel, Field


class WireExplanation(BaseModel):
    borrower_text: str = Field(description="The explanation, in the requested language.")
    english_text: str = Field(
        default="",
        description="The same explanation in English, sentence for sentence, for the loan "
        "officer to check. Empty when the requested language is English.",
    )
