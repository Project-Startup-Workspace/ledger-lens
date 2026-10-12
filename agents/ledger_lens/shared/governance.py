"""Model governance records shared by the risk agent, AuditPulse and the audit pack.

Read straight from the artifact JSON, so no agent needs another agent's internals.
"""

import json
from pathlib import Path
from typing import Any

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
        artifact = _read_json(path)
        if artifact.get("version") == version:
            metrics = artifact.get("metrics")
            auc = metrics.get("holdout_auc") if isinstance(metrics, dict) else None
            return ModelRecord(
                version=version,
                validation_auc=auc if _is_auc(auc) else None,
                bias_report=bool(_read_json(bias_report_path(path))),
            )
    return ModelRecord(version=version, validation_auc=None, bias_report=False)


def _read_json(path: Path) -> dict[str, Any]:
    """A JSON object from `path`, or {} when it is missing or malformed."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_auc(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 < value <= 1
