"""Explanation agent: an officer report and a borrower explanation for one case.

The officer report is assembled from the current case on demand, so it never goes
stale and never contains anything the agents did not produce. Only the borrower text
is written by Gemini, from a short list of checked facts. Its output is screened and
every number in it must appear in those facts; otherwise the English template is used.
"""

import logging
import re

from ledger_lens.explain import prompts
from ledger_lens.explain.schemas import WireExplanation
from ledger_lens.shared.config import LlmProvider, Settings
from ledger_lens.shared.llm import LlmClient, LlmError, LlmUnavailableError
from ledger_lens.shared.safety import SafetyScreen
from ledger_lens.shared.schemas import CreditFile, Explanation, FindingStatus

log = logging.getLogger(__name__)

TEMPLATE = "template"
_NUMBER = re.compile(r"\d[\d,.\s]*\d|\d")
_RECOMMENDATION_WORDS = {
    "approve": "looks strong enough to recommend",
    "refer": "needs a closer look by the loan officer",
    "decline": "does not yet meet the lender's usual standard",
}


class UnsupportedLanguageError(ValueError):
    pass


def normalise_language(language: str) -> str:
    """'EN', 'en-LK' and 'en_lk' all mean 'en'; anything unsupported is rejected."""
    code = language.strip().lower().replace("_", "-").split("-")[0]
    if code not in prompts.LANGUAGES:
        supported = ", ".join(sorted(prompts.LANGUAGES))
        raise UnsupportedLanguageError(f"language '{language}' is not supported ({supported})")
    return code


class ExplainAgent:
    def __init__(self, llm: LlmClient, safety: SafetyScreen, settings: Settings) -> None:
        self._llm = llm
        self._safety = safety
        self._settings = settings
        self._can_speak = settings.enable_tts and settings.llm_provider is not LlmProvider.OFFLINE

    def explain(self, case: CreditFile, language: str | None = None) -> Explanation:
        """Write the borrower explanation; `language` defaults to the applicant's own."""
        target = normalise_language(language or case.applicant.preferred_language)
        facts = borrower_facts(case)
        text, written_by = self._borrower_text(target, facts)
        actual = target if written_by != TEMPLATE else "en"
        return Explanation(
            borrower_text=text,
            borrower_language=actual,
            # Only model-written text counts as translated; template text never does.
            translated=written_by != TEMPLATE,
            audio_available=self._can_speak and actual in prompts.TTS_LOCALES,
            written_by=written_by,
        )

    def speak(self, text: str, language: str) -> bytes:
        """WAV audio of the borrower explanation, for reading it aloud."""
        locale = prompts.TTS_LOCALES.get(normalise_language(language))
        if not self._can_speak or locale is None:
            raise LlmUnavailableError(f"speech is not available for '{language}'")
        return self._llm.speak(text=text, language=locale)

    def _borrower_text(self, language: str, facts: list[str]) -> tuple[str, str]:
        try:
            wire = self._llm.generate(
                task="explain_borrower",
                model=self._settings.model_reason,
                system=prompts.SYSTEM,
                prompt=prompts.borrower_prompt(language, "\n".join(f"- {f}" for f in facts)),
                schema=WireExplanation,
            )
        except LlmUnavailableError:
            return template_text(facts), TEMPLATE
        except LlmError:
            log.warning("borrower explanation failed; using the English template", exc_info=True)
            return template_text(facts), TEMPLATE
        text = wire.borrower_text.strip()
        if problem := self._reject_reason(text, facts):
            log.warning("borrower explanation rejected", extra={"reason": problem})
            return template_text(facts), TEMPLATE
        return text, f"{self._settings.model_reason}/{prompts.PROMPT_VERSION}"

    def _reject_reason(self, text: str, facts: list[str]) -> str | None:
        """Why model text must not reach the borrower, or None when it is acceptable."""
        if not text:
            return "empty"
        if len(text.split()) > 2 * prompts.MAX_WORDS:
            return "too long"
        if self._safety.screen(text).flagged:
            return "failed safety screen"
        known = {_digits(n) for n in _NUMBER.findall(" ".join(facts))}
        invented = {_digits(n) for n in _NUMBER.findall(text)} - known
        # Small counts ("3 reasons", "2 weeks") are fine; amounts must come from the facts.
        if any(len(n) > 2 for n in invented):
            return "number not in the facts"
        return None


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


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
    """Markdown summary of the case as it stands now, for the officer and the audit pack."""
    lines = [f"# Credit file {case.case_id}", ""]
    lines.append(
        f"**Applicant:** {case.applicant.business_name} ({case.applicant.business_type}), "
        f"{case.applicant.years_in_business:g} years trading.  "
    )
    lines.append(
        f"**Request:** {case.loan.amount:,.0f} {case.loan.currency} over "
        f"{case.loan.tenor_months} months at {case.loan.annual_rate_pct:g}% a year."
    )
    warnings = [(x.evidence_id, w) for x in case.extractions for w in x.warnings]
    if warnings:
        lines += ["", "## Evidence warnings"]
        lines += [f"- `{evidence_id}`: {warning}" for evidence_id, warning in warnings]
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
            lines.append("Not verified against a statement.")
        else:
            lines.append(f"{len(check.flags)} of {check.weeks_compared} weeks flagged.")
            lines += [
                f"- **{f.severity}**: {f.explanation} Ask: _{f.officer_question}_"
                for f in check.flags
            ]
        lines += [f"- Note: {note}" for note in check.notes]
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
    if decision := case.decision:
        lines += [
            "",
            "## Decision",
            f"**{decision.outcome}** by `{decision.officer_id}`"
            + (" (overrides the recommendation)" if decision.overridden else "")
            + f": {decision.reason}",
        ]
    return "\n".join(lines) + "\n"
