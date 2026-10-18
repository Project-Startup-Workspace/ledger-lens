"""Model governance records shared by the risk agent, AuditPulse and the audit pack.

Read straight from the artifact JSON, so no agent needs another agent's internals.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ledger_lens.shared.schemas import MODEL_VERSION_PATTERN

_SAFE_VERSION = re.compile(MODEL_VERSION_PATTERN)


class ModelRecord(BaseModel):
    version: str
    validation_auc: float | None
    bias_report: bool


def bias_report_path(artifact: Path) -> Path:
    """Where the evaluation suite writes the bias test for a model artifact."""
    return artifact.with_suffix(".bias.json")


def artifact_fingerprint(artifact: Path) -> str:
    """Hash of the artifact's bytes; a retrained model gets a new fingerprint."""
    return hashlib.sha256(artifact.read_bytes()).hexdigest()


def has_passing_bias_report(artifact: Path) -> bool:
    """A bias report counts only if it was run on exactly this artifact and passed."""
    report = _read_json(bias_report_path(artifact))
    return bias_report_matches(artifact) and report.get("passes_four_fifths") is True


def artifact_for_version(
    active_artifact: Path, version: str, fingerprint: str | None = None
) -> Path | None:
    """The artifact file for `version`: the active one, or `<version>.json` beside it.

    With `fingerprint`, only the exact artifact counts: a model retrained under the same
    version name is a different model.
    """
    candidates = [active_artifact]
    if _SAFE_VERSION.fullmatch(version):  # the version names a file only when it is safe
        candidates.append(active_artifact.parent / f"{version}.json")
    for path in candidates:
        if _read_json(path).get("version") != version:
            continue
        if fingerprint is None or artifact_fingerprint(path) == fingerprint:
            return path
    return None


def bias_report_matches(artifact: Path) -> bool:
    """True when the bias report beside `artifact` was run on exactly this artifact."""
    report = _read_json(bias_report_path(artifact))
    return report.get("model_fingerprint") == artifact_fingerprint(artifact)


def model_record(
    active_artifact: Path, version: str | None, fingerprint: str | None = None
) -> ModelRecord | None:
    """Governance record for the exact artifact that scored a case.

    Usually that is the active artifact. A case scored by an earlier version is looked
    up as `<version>.json` beside it; if that artifact is gone or was replaced (another
    fingerprint), the record shows no metrics, as the audit pack's model card does.
    """
    if not version:
        return None
    path = artifact_for_version(active_artifact, version, fingerprint)
    if path is None:
        return ModelRecord(version=version, validation_auc=None, bias_report=False)
    metrics = _read_json(path).get("metrics")
    auc = metrics.get("holdout_auc") if isinstance(metrics, dict) else None
    return ModelRecord(
        version=version,
        validation_auc=auc if _is_auc(auc) else None,
        bias_report=has_passing_bias_report(path),
    )


def _read_json(path: Path) -> dict[str, Any]:
    """A JSON object from `path`, or {} when it is missing or malformed."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_auc(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 < value <= 1
