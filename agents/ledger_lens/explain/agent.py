"""Explanation agent: an officer report and a borrower explanation for one case.

The officer report is assembled from the case deterministically, so it never contains
anything the agents did not produce. Only the borrower text is written by Gemini, from
a short list of checked facts; without a model it falls back to an English template.
"""

import logging

from ledger_lens.explain import prompts
from ledger_lens.explain.schemas import WireExplanation
from ledger_lens.shared.config import Settings
from ledger_lens.shared.llm import LlmClient, LlmError, LlmUnavailableError
from ledger_lens.shared.schemas import CreditFile, Explanation, FindingStatus

log = logging.getLogger(__name__)

_RECOMMENDATION_WORDS = {
    "approve": "looks strong enough to recommend",
    "refer": "needs a closer look by the loan officer",
    "decline": "does not yet meet the lender's usual standard",
}


class ExplainAgent:
    def __init__(self, llm: LlmClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def explain(self, case: CreditFile, language: str | None = None) -> Explanation:
        """Write both explanations; `language` defaults to the applicant's preference."""
        target = language or case.applicant.preferred_language
        facts = borrower_facts(case)
        text, translated = self._borrower_text(target, facts)
        return Explanation(
            officer_report=officer_report(case),
            borrower_text=text,
            borrower_language=target if translated else "en",
            translated=translated,
            audio_available=self._settings.enable_tts and translated,
        )

    def speak(self, text: str, language: str) -> bytes:
        """WAV audio of the borrower explanation, for reading it aloud."""
        if not self._settings.enable_tts:
            raise LlmUnavailableError("speech is turned off (LL_ENABLE_TTS=false)")
        return self._llm.speak(text=text, language=language)

    def _borrower_text(self, language: str, facts: list[str]) -> tuple[str, bool]:
        try:
            wire = self._llm.generate(
                task="explain_borrower",
                model=self._settings.model_reason,
                system=prompts.SYSTEM,
                prompt=prompts.borrower_prompt(language, "\n".join(f"- {f}" for f in facts)),
                schema=WireExplanation,
            )
            return wire.borrower_text.strip(), True
        except (LlmUnavailableError, LlmError) as exc:
            log.info("borrower explanation fell back to template", extra={"reason": str(exc)})
            return template_text(facts), language == "en"


def borrower_facts(case: CreditFile) -> list[str]:
    """Short, checked statements the borrower explanation may use, and nothing else."""
    facts = [f"Loan requested: {case.loan.amount:,.0f} {case.loan.currency}."]
    if flow := case.cash_flow:
        facts.append(
            f"Records cover {flow.weeks_covered} weeks: average weekly sales "
            f"{flow.avg_weekly_sales:,.0f} and money left after expenses "
            f"{flow.avg_weekly_net:,.0f} {flow.currency} a week."
        )
    if risk := case.risk:
        facts.append(f"Assessment: the application {_RECOMMENDATION_WORDS[risk.recommendation]}.")
        facts += [reason.text for reason in risk.reasons[:3]]
        facts += [f"Could help: {step.text}" for step in risk.path_to_approval]
    if case.consistency and case.consistency.flags:
        facts.append(
            f"{len(case.consistency.flags)} week(s) in the notebook differ from the wallet "
            "statement; the officer will ask about them."
        )
    facts.append("A loan officer makes the final decision.")
    return facts


def template_text(facts: list[str]) -> str:
    return "Thank you for your application. Here is what we found.\n\n" + "\n".join(
        f"• {fact}" for fact in facts
    )


def officer_report(case: CreditFile) -> str:
    """Markdown summary of every agent's output, for the officer and the audit pack."""
    lines = [f"# Credit file {case.case_id}", ""]
    lines.append(
        f"**Applicant:** {case.applicant.business_name} ({case.applicant.business_type}), "
        f"{case.applicant.years_in_business:g} years trading.  "
    )
    lines.append(
        f"**Request:** {case.loan.amount:,.0f} {case.loan.currency} over "
        f"{case.loan.tenor_months} months at {case.loan.annual_rate_pct:g}% a year."
    )
    if flow := case.cash_flow:
        lines += [
            "",
            "## Cash flow",
            f"{flow.weeks_covered} weeks; average weekly sales {flow.avg_weekly_sales:,.0f}, "
            f"net {flow.avg_weekly_net:,.0f} {flow.currency}; sales vary by "
            f"{flow.sales_volatility:.0%}. {len(flow.entries_for_review)} line(s) need review.",
        ]
    if check := case.consistency:
        lines += ["", "## Consistency"]
        if check.status == "insufficient_data":
            lines.append("Not verified: " + " ".join(check.notes or ["no statement compared."]))
        else:
            lines.append(f"{len(check.flags)} of {check.weeks_compared} weeks flagged.")
            lines += [
                f"- **{f.severity}**: {f.explanation} Ask: _{f.officer_question}_"
                for f in check.flags
            ]
    if risk := case.risk:
        lines += [
            "",
            "## Risk",
            f"Grade **{risk.grade}** (probability of default {risk.probability_of_default:.1%}), "
            f"recommendation **{risk.recommendation}**, model `{risk.model_version}`"
            + (" (illustrative)." if risk.illustrative else "."),
        ]
        lines += [f"- {r.text}" for r in risk.reasons]
        if risk.path_to_approval:
            lines += ["", "Path to approval:"] + [f"- {s.text}" for s in risk.path_to_approval]
    if report := case.compliance:
        open_items = [
            f for f in report.findings if f.status in {FindingStatus.FAIL, FindingStatus.REVIEW}
        ]
        lines += [
            "",
            f"## Compliance ({report.jurisdiction_name}, {report.rule_pack_version})",
            f"{report.count(FindingStatus.PASS)} passed, {report.count(FindingStatus.FAIL)} "
            f"failed, {report.count(FindingStatus.REVIEW)} for review, "
            f"{report.count(FindingStatus.PENDING)} pending.",
        ]
        lines += [f"- {f.rule_id} {f.title}: {f.detail}" for f in open_items]
    return "\n".join(lines) + "\n"
