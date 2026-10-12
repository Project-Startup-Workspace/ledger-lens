"""Officer report and borrower explanation, with and without a model."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from ledger_lens.explain.agent import ExplainAgent, borrower_facts, officer_report
from ledger_lens.explain.schemas import WireExplanation
from ledger_lens.shared.config import Settings
from ledger_lens.shared.llm import Attachment, LlmUnavailableError, build_llm
from ledger_lens.shared.schemas import (
    Applicant,
    CashFlowSummary,
    Consent,
    CounterfactualStep,
    CreditFile,
    LoanRequest,
    ReasonCode,
    RiskGrade,
    RiskResult,
)


def assessed_case() -> CreditFile:
    return CreditFile(
        jurisdiction="lk",
        applicant=Applicant(
            full_name="Kamala Perera",
            date_of_birth="1979-11-02",
            national_id="797063456V",
            phone="0771234567",
            business_name="Kamala Stores",
            business_type="grocery shop",
            years_in_business=11,
            preferred_language="ta",
        ),
        loan=LoanRequest(
            amount=Decimal(250_000),
            currency="LKR",
            tenor_months=18,
            annual_rate_pct=28,
            purpose="x",
        ),
        consent=Consent(given=True),
        cash_flow=CashFlowSummary(
            currency="LKR",
            weeks=[],
            total_sales=Decimal(800_000),
            total_expenses=Decimal(600_000),
            avg_weekly_sales=Decimal(100_000),
            avg_weekly_net=Decimal(25_000),
            sales_volatility=0.1,
            weeks_covered=8,
        ),
        risk=RiskResult(
            model_version="risk-local-v1",
            probability_of_default=0.14,
            grade=RiskGrade.C,
            recommendation="refer",
            features={},
            reasons=[
                ReasonCode(
                    feature="weeks_of_records",
                    label="Weeks",
                    value=8,
                    contribution=0.5,
                    text="8 weeks of records, which raises the risk.",
                )
            ],
            path_to_approval=[
                CounterfactualStep(
                    feature="weeks_of_records",
                    label="Weeks",
                    current=8,
                    target=20,
                    text="Bring 12 more weeks of records (20 in total).",
                    sufficient=True,
                )
            ],
        ),
    )


class RecordingLlm:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(
        self, *, prompt: str, schema: Any, attachments: Sequence[Attachment] = (), **_: Any
    ) -> Any:
        self.prompts.append(prompt)
        return WireExplanation(borrower_text="வணக்கம்")

    def speak(self, *, text: str, language: str) -> bytes:
        return b"RIFF"


def test_borrower_text_uses_the_model_in_the_applicant_language(settings: Settings) -> None:
    llm = RecordingLlm()
    explanation = ExplainAgent(llm, settings).explain(assessed_case())
    assert (explanation.borrower_text, explanation.borrower_language) == ("வணக்கம்", "ta")
    assert explanation.translated and explanation.audio_available
    assert "Language: Tamil" in llm.prompts[0]


def test_prompt_carries_checked_facts_but_no_personal_identifiers(settings: Settings) -> None:
    llm = RecordingLlm()
    ExplainAgent(llm, settings).explain(assessed_case())
    prompt = llm.prompts[0]
    assert "Bring 12 more weeks" in prompt
    assert "Kamala" not in prompt and "797063456V" not in prompt and "0771234567" not in prompt


def test_offline_falls_back_to_english_template(settings: Settings) -> None:
    explanation = ExplainAgent(build_llm(settings), settings).explain(assessed_case())
    assert not explanation.translated and explanation.borrower_language == "en"
    assert not explanation.audio_available
    assert "A loan officer makes the final decision." in explanation.borrower_text


def test_speech_respects_the_feature_flag(settings: Settings) -> None:
    settings.enable_tts = False
    with pytest.raises(LlmUnavailableError):
        ExplainAgent(RecordingLlm(), settings).speak("hi", "en")


def test_officer_report_summarises_every_agent() -> None:
    report = officer_report(assessed_case())
    for heading in ("# Credit file", "## Cash flow", "## Risk", "Path to approval"):
        assert heading in report
    assert "(illustrative)" in report


def test_borrower_facts_always_state_who_decides() -> None:
    assert borrower_facts(assessed_case())[-1] == "A loan officer makes the final decision."
