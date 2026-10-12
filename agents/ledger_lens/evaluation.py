"""Evaluation suite: read accuracy per script, and a fairness check on the risk model.

Run: `cd agents && uv run python -m ledger_lens.evaluation`. With the default offline
provider it measures the recorded responses; set LL_LLM_PROVIDER to measure Gemini.
Writes eval/results/latest.{json,md} and the model's bias report next to its artifact.
"""

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.config import REPO_ROOT, Settings, get_settings
from ledger_lens.shared.governance import bias_report_path
from ledger_lens.shared.llm import build_llm
from ledger_lens.shared.safety import build_safety_screen
from ledger_lens.shared.schemas import EvidenceDocument, EvidenceKind, LedgerEntry

DEMO = REPO_ROOT / "demo-data"
RESULTS = REPO_ROOT / "eval" / "results"
TRAINING_CSV = REPO_ROOT / "ml" / "data" / "synthetic_applicants.csv"
APPROVAL_PD = 0.10  # grades A and B
FOUR_FIFTHS = 0.8


class ScriptAccuracy(BaseModel):
    script: str  # writing system and language, e.g. "Latin (vi)"
    pages: int
    labelled_lines: int
    lines_found: float  # share of labelled lines matched by date and direction
    amounts_exact: float  # share of labelled lines read with the exact amount
    flagged_for_review: float  # share of extracted lines below the confidence threshold
    wrong_but_confident: int  # amount wrong yet above the threshold: the dangerous case


class BiasReport(BaseModel):
    model_version: str
    approval_threshold_pd: float
    groups: dict[str, dict[str, float]]
    four_fifths_ratio: float
    passes_four_fifths: bool


def read_accuracy(settings: Settings) -> list[ScriptAccuracy]:
    agent = EvidenceAgent(build_llm(settings), build_safety_screen(settings), settings)
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for label_path in sorted(DEMO.glob("synthetic-*/labels/notebook-p*.json")):
        labels = json.loads(label_path.read_text(encoding="utf-8"))
        image = label_path.parent.parent / labels["image"]
        currency = json.loads((image.parent / "case.json").read_text())["loan"]["currency"]
        doc = EvidenceDocument(
            kind=EvidenceKind.NOTEBOOK,
            filename=image.name,
            content_type="image/png",
            sha256="-",
            blob_key=image.name,
        )
        result = agent.read(
            doc, image.read_bytes(), reference_date=date(2026, 10, 12), currency=currency
        )
        key = f"{labels['script']} ({result.language})"
        score_page(totals[key], labels["entries"], result.entries, settings)
    return [
        ScriptAccuracy(
            script=script,
            pages=t["pages"],
            labelled_lines=t["labels"],
            lines_found=round(t["found"] / t["labels"], 4),
            amounts_exact=round(t["exact"] / t["labels"], 4),
            flagged_for_review=round(t["low"] / max(t["extracted"], 1), 4),
            wrong_but_confident=t["wrong_confident"],
        )
        for script, t in sorted(totals.items())
    ]


def score_page(
    totals: dict[str, int],
    labels: list[dict[str, Any]],
    entries: list[LedgerEntry],
    settings: Settings,
) -> None:
    """Match each labelled line to an unused extracted line with the same date and direction."""
    unused = list(entries)
    totals["pages"] += 1
    totals["labels"] += len(labels)
    totals["extracted"] += len(entries)
    totals["low"] += sum(e.confidence < settings.min_extraction_confidence for e in entries)
    for label in labels:
        candidates = [
            e
            for e in unused
            if e.entry_date.isoformat() == label["date"] and e.direction == label["direction"]
        ]
        if not candidates:
            continue
        match = min(candidates, key=lambda e: abs(float(e.amount) - label["amount"]))
        unused.remove(match)
        totals["found"] += 1
        if float(match.amount) == label["amount"]:
            totals["exact"] += 1
        elif match.confidence >= settings.min_extraction_confidence:
            totals["wrong_confident"] += 1


def bias_check(model: LogisticModel, rows_path: Path = TRAINING_CSV) -> BiasReport:
    """Approval rate per group on the synthetic applicants, and the four-fifths ratio.

    The group attribute is never a model input; this checks the model does not
    disadvantage a group through other features.
    """
    probabilities: dict[str, list[float]] = defaultdict(list)
    with rows_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            features = {name: float(row[name]) for name in model.features}
            probabilities[row["group_attr"]].append(model.probability(features))
    groups = {
        group: {
            "applicants": float(len(values)),
            "approval_rate": round(sum(p < APPROVAL_PD for p in values) / len(values), 4),
            "mean_probability_of_default": round(statistics.fmean(values), 4),
        }
        for group, values in sorted(probabilities.items())
    }
    rates = [g["approval_rate"] for g in groups.values()]
    ratio = round(min(rates) / max(rates), 4) if max(rates) else 0.0
    return BiasReport(
        model_version=model.version,
        approval_threshold_pd=APPROVAL_PD,
        groups=groups,
        four_fifths_ratio=ratio,
        passes_four_fifths=ratio >= FOUR_FIFTHS,
    )


def markdown(provider: str, accuracy: list[ScriptAccuracy], bias: BiasReport) -> str:
    lines = [
        "# Evaluation results",
        "",
        f"Provider: `{provider}`. Regenerate with `make eval`.",
        "",
        "## Read accuracy per script",
        "",
        "| Script (language) | Pages | Lines | Found | Exact amount | Sent to review "
        "| Wrong but confident |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {a.script} | {a.pages} | {a.labelled_lines} | {a.lines_found:.0%} | "
        f"{a.amounts_exact:.0%} | {a.flagged_for_review:.0%} | {a.wrong_but_confident} |"
        for a in accuracy
    ]
    lines += [
        "",
        f"## Fairness: `{bias.model_version}`",
        "",
        "| Group | Applicants | Approval rate | Mean PD |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {name} | {g['applicants']:.0f} | {g['approval_rate']:.1%} | "
        f"{g['mean_probability_of_default']:.1%} |"
        for name, g in bias.groups.items()
    ]
    verdict = "passes" if bias.passes_four_fifths else "FAILS"
    lines += ["", f"Four-fifths ratio {bias.four_fifths_ratio:.2f}: {verdict}.", ""]
    return "\n".join(lines)


def main() -> None:
    settings = get_settings()
    model = LogisticModel.load(settings.risk_model_path)
    accuracy = read_accuracy(settings)
    bias = bias_check(model)
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": settings.llm_provider,
        "read_accuracy": [a.model_dump() for a in accuracy],
        "bias": bias.model_dump(),
    }
    (RESULTS / "latest.json").write_text(json.dumps(payload, indent=2) + "\n")
    (RESULTS / "latest.md").write_text(markdown(settings.llm_provider, accuracy, bias))
    bias_report_path(settings.risk_model_path).write_text(bias.model_dump_json(indent=2) + "\n")
    print(markdown(settings.llm_provider, accuracy, bias))


if __name__ == "__main__":
    main()
