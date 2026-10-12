"""Builds the facts that rule checks read. Every fact a pack may use is defined here.

| Fact | Type | Meaning |
|---|---|---|
| lender.licence | str or None | Licence number configured for this jurisdiction |
| consent.given | bool | Applicant consent recorded |
| consent.before_evidence | bool | Consent recorded no later than the first evidence upload |
| applicant.age | int | Whole years at the case date |
| screening.matches | list[str] | Sanctions-list names similar to the applicant or guarantor |
| disclosure.apr_pct, .instalment, .instalments | number | Key Fact Statement terms |
| disclosure.blank_fields | list[str] | Unfilled agreement fields at signature |
| disclosure.acknowledged | bool | Borrower acknowledged the Key Fact Statement |
| disclosure.acknowledged_before_decision | bool | ...and did so no later than the decision |
| decision.officer_id, decision.reason | str or None | The officer's sign-off |
| risk.reason_count | int | Reason codes attached to the score |
| model.version, model.validation_auc | str, float | Model governance record |
| model.bias_report | bool | A bias test exists for this model version |
| storage.region | str | Where case data is stored ("local" in development) |
"""

from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ledger_lens.auditpulse.screening import ScreeningHit
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.config import Backend, Settings
from ledger_lens.shared.schemas import CreditFile


class ModelRecord(BaseModel):
    version: str
    validation_auc: float | None
    bias_report: bool


def bias_report_path(artifact: Path) -> Path:
    """Where the evaluation suite writes the bias test for a model artifact."""
    return artifact.with_suffix(".bias.json")


def model_record(active_artifact: Path, version: str | None) -> ModelRecord | None:
    """Governance record for the model version that scored the case.

    Usually that is the active artifact. A case scored by an earlier version is looked
    up as `<version>.json` beside it; if that file is gone, the record shows no metrics.
    """
    if not version:
        return None
    candidates = [active_artifact, active_artifact.parent / f"{version}.json"]
    for path in candidates:
        if path.exists():
            model = LogisticModel.load(path)
            if model.version == version:
                return ModelRecord(
                    version=version,
                    validation_auc=model.metrics.get("holdout_auc"),
                    bias_report=bias_report_path(path).exists(),
                )
    return ModelRecord(version=version, validation_auc=None, bias_report=False)


def age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def build_facts(
    case: CreditFile,
    jurisdiction: str,
    settings: Settings,
    screening: list[ScreeningHit],
    model: ModelRecord | None,
) -> dict[str, Any]:
    disclosure = case.disclosure
    decision = case.decision
    return {
        "lender": {"licence": settings.lender_licences.get(jurisdiction)},
        "consent": {
            "given": case.consent.given,
            "before_evidence": all(
                case.consent.recorded_at <= doc.uploaded_at for doc in case.evidence
            ),
        },
        "applicant": {"age": age_on(case.applicant.date_of_birth, case.created_at.date())},
        "screening": {"matches": sorted({hit.listed.name for hit in screening})},
        "disclosure": {
            "apr_pct": disclosure.apr_pct,
            "instalment": float(disclosure.instalment),
            "instalments": disclosure.instalments,
            "blank_fields": disclosure.blank_fields,
            "acknowledged": disclosure.acknowledged_at is not None,
            "acknowledged_before_decision": disclosure.acknowledged_at is not None
            and (decision is None or disclosure.acknowledged_at <= decision.decided_at),
        }
        if disclosure
        else {},
        "decision": {"officer_id": decision.officer_id, "reason": decision.reason.strip() or None}
        if decision
        else {},
        "risk": {"reason_count": len(case.risk.reasons)} if case.risk else {},
        "model": model.model_dump() if model else {},
        "storage": {
            "region": settings.gcp_region if settings.storage_backend is Backend.GCP else "local"
        },
    }
