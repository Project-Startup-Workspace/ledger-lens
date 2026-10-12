"""Model governance records shared by the risk agent, AuditPulse and the audit pack.

Read straight from the artifact JSON, so no agent needs another agent's internals.
"""

import json
from pathlib import Path

from pydantic import BaseModel


class ModelRecord(BaseModel):
    version: str
    validation_auc: float | None
    bias_report: bool


def bias_report_path(artifact: Path) -> Path:
    """Where the evaluation suite writes the bias test for a model artifact."""
    return artifact.with_suffix(".bias.json")


def model_record(active_artifact: Path, version: str | None) -> ModelRecord | None:
    """Governance record for the model version that scored a case.

    Usually that is the active artifact. A case scored by an earlier version is looked
    up as `<version>.json` beside it; if that file is gone, the record shows no metrics.
    """
    if not version:
        return None
    for path in (active_artifact, active_artifact.parent / f"{version}.json"):
        if not path.exists():
            continue
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("version") == version:
            return ModelRecord(
                version=version,
                validation_auc=artifact.get("metrics", {}).get("holdout_auc"),
                bias_report=bias_report_path(path).exists(),
            )
    return ModelRecord(version=version, validation_auc=None, bias_report=False)
