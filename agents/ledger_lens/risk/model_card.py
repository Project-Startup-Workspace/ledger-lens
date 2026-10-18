"""AI inventory entry and validation summary for a model version.

Generated from the artifact itself, so the paperwork MAS-style guidelines ask for can
never drift from the model actually in use.
"""

import json
from pathlib import Path
from typing import Any

from ledger_lens.risk.features import BY_NAME
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.governance import bias_report_matches, bias_report_path


def model_card(model: LogisticModel, artifact: Path) -> dict[str, Any]:
    """Inventory entry, training summary, features and fairness results for `artifact`."""
    bias = _bias_section(artifact)
    return {
        "inventory": {
            "name": "Ledger Lens default-risk model",
            "version": model.version,
            "purpose": "Recommend a risk grade for micro-enterprise loans; officers decide.",
            "materiality": "high (credit decisions)",
            "type": "logistic regression",
            "human_oversight": "Every decision is made and signed by a loan officer.",
            "status": "illustrative, synthetic training data" if model.illustrative else "live",
        },
        "training": {"data": model.trained_on, "metrics": model.metrics},
        "features": [
            {"name": name, "meaning": BY_NAME[name].label, "coefficient": round(c, 4)}
            for name, c in zip(model.features, model.coefficients, strict=True)
        ],
        "explainability": "Exact Shapley values per feature, reported as reason codes.",
        "fairness": bias or {"status": "not yet run"},
    }


def _bias_section(artifact: Path) -> dict[str, Any] | None:
    """The bias report, marked with whether it was run on this exact artifact.

    A report left over from an earlier training run must not pass as this model's;
    whether it passed is stated in the report itself.
    """
    path = bias_report_path(artifact)
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"status": "bias report unreadable"}
    if not isinstance(report, dict):
        return {"status": "bias report unreadable"}
    return report | {"valid_for_this_artifact": bias_report_matches(artifact)}
