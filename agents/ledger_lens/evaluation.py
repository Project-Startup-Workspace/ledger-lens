"""Evaluation suite: read accuracy per script, and a fairness check on the risk model.

Run: `cd agents && uv run python -m ledger_lens.evaluation`. With the default offline
provider it measures the recorded responses; set LL_LLM_PROVIDER to measure Gemini.
Writes eval/results/latest.{json,md} and the model's bias report next to its artifact.
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ledger_lens.evidence.agent import EvidenceAgent
from ledger_lens.risk.agent import APPROVE_GRADES, grade_for
from ledger_lens.risk.model import LogisticModel
from ledger_lens.shared.config import REPO_ROOT, Settings, get_settings
from ledger_lens.shared.governance import artifact_fingerprint, bias_report_path
from ledger_lens.shared.llm import build_llm
from ledger_lens.shared.safety import build_safety_screen
from ledger_lens.shared.schemas import EvidenceDocument, EvidenceKind, LedgerEntry

DEMO = REPO_ROOT / "demo-data"
RESULTS = REPO_ROOT / "eval" / "results"
TRAINING_CSV = REPO_ROOT / "ml" / "data" / "synthetic_applicants.csv"
FOUR_FIFTHS = 0.8


class ScriptAccuracy(BaseModel):
    script: str  # labelled writing system and language, e.g. "Latin (vi)"
    pages: int
    labelled_lines: int
    lines_found: float  # share of labelled lines matched by date and direction
    amounts_exact: float  # share of labelled lines read with the exact amount
    flagged_for_review: float  # share of extracted lines below the confidence threshold
    language_detected: float  # share of pages whose language the model identified correctly
    # Lines that reach the totals with a wrong amount, or that match no labelled line at
    # all (invented, or wrong date or direction). The dangerous errors; target 0.
    wrong_but_confident: int


class BiasReport(BaseModel):
    model_version: str
    model_fingerprint: str  # ties the report to the exact artifact it was run on
    rows: str
    groups: dict[str, dict[str, float]]
    four_fifths_ratio: float
    passes_four_fifths: bool


def read_accuracy(settings: Settings) -> list[ScriptAccuracy]:
    agent = EvidenceAgent(build_llm(settings), build_safety_screen(settings), settings)
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for label_path in sorted(DEMO.glob("synthetic-*/labels/notebook-p*.json")):
        labels = json.loads(label_path.read_text(encoding="utf-8"))
        image = label_path.parent.parent / labels["image"]
        case = json.loads((image.parent / "case.json").read_text(encoding="utf-8"))
        language = case["applicant"]["preferred_language"]
        doc = EvidenceDocument(
            kind=EvidenceKind.NOTEBOOK,
            filename=image.name,
            content_type="image/png",
            sha256="-",
            blob_key=image.name,
        )
        # The page's own last date stands in for the case date, so labels of any age work.
        reference = max(date.fromisoformat(e["date"]) for e in labels["entries"])
        result = agent.read(
            doc, image.read_bytes(), reference_date=reference, currency=case["loan"]["currency"]
        )
        bucket = totals[f"{labels['script']} ({language})"]
        bucket["language_ok"] += result.language == language
        score_page(bucket, labels["entries"], result.entries, settings)
    return [
        ScriptAccuracy(
            script=script,
            pages=t["pages"],
            labelled_lines=t["labels"],
            lines_found=round(t["found"] / t["labels"], 4),
            amounts_exact=round(t["exact"] / t["labels"], 4),
            flagged_for_review=round(t["low"] / max(t["extracted"], 1), 4),
            language_detected=round(t["language_ok"] / t["pages"], 4),
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
    """Pair labelled and extracted lines with the same date and direction.

    Exact amounts are paired first, then the remaining lines by closest amount, so one
    label can never take an entry another label matches exactly.
    """
    threshold = settings.min_extraction_confidence
    totals["pages"] += 1
    totals["labels"] += len(labels)
    totals["extracted"] += len(entries)
    totals["low"] += sum(e.confidence < threshold for e in entries)

    unused = list(entries)
    open_labels = list(labels)

    def same_line(label: dict[str, Any], entry: LedgerEntry) -> bool:
        return bool(
            entry.entry_date.isoformat() == label["date"] and entry.direction == label["direction"]
        )

    for exact in (True, False):
        for label in list(open_labels):
            candidates = [e for e in unused if same_line(label, e)]
            if exact:
                candidates = [e for e in candidates if float(e.amount) == label["amount"]]
            if not candidates:
                continue
            match = min(candidates, key=lambda e: abs(float(e.amount) - label["amount"]))
            unused.remove(match)
            open_labels.remove(label)
            totals["found"] += 1
            if exact:
                totals["exact"] += 1
            elif match.confidence >= threshold:
                totals["wrong_confident"] += 1
    # Confident lines matching no label still reach the totals: count them as errors.
    totals["wrong_confident"] += sum(e.confidence >= threshold for e in unused)


def bias_check(model: LogisticModel, artifact: Path, rows_path: Path = TRAINING_CSV) -> BiasReport:
    """Approval rate per group on the holdout applicants, and the four-fifths ratio.

    Approval uses the risk agent's own grade bands. The group attribute is never a model
    input; this checks the model does not disadvantage a group through other features.
    """
    probabilities: dict[str, list[float]] = defaultdict(list)
    with rows_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("is_holdout", "true") != "true":
                continue  # training rows would flatter the model
            features = {name: float(row[name]) for name in model.features}
            probabilities[row["group_attr"]].append(model.probability(features))
    groups = {
        group: {
            "applicants": float(len(values)),
            "approval_rate": round(
                sum(grade_for(p) in APPROVE_GRADES for p in values) / len(values), 4
            ),
            "mean_probability_of_default": round(statistics.fmean(values), 4),
        }
        for group, values in sorted(probabilities.items())
    }
    rates: list[float] = [g["approval_rate"] for g in groups.values()]
    top = max(rates, default=0.0)
    ratio = round(min(rates) / top, 4) if top else 0.0
    return BiasReport(
        model_version=model.version,
        model_fingerprint=artifact_fingerprint(artifact),
        rows="holdout",
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
        "| Language detected | Wrong but confident |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {a.script} | {a.pages} | {a.labelled_lines} | {a.lines_found:.0%} | "
        f"{a.amounts_exact:.0%} | {a.flagged_for_review:.0%} | {a.language_detected:.0%} "
        f"| {a.wrong_but_confident} |"
        for a in accuracy
    ]
    lines += [
        "",
        f"## Fairness: `{bias.model_version}` ({bias.rows} rows)",
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


def main() -> int:
    """Run both checks; exit 1 if any gate fails, so CI turns red."""
    settings = get_settings()
    artifact = settings.risk_model_path
    model = LogisticModel.load(artifact)
    accuracy = read_accuracy(settings)
    bias = bias_check(model, artifact)
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": settings.llm_provider,
        "read_accuracy": [a.model_dump() for a in accuracy],
        "bias": bias.model_dump(),
    }
    report = markdown(settings.llm_provider, accuracy, bias)
    (RESULTS / "latest.json").write_text(json.dumps(payload, indent=2) + "\n")
    (RESULTS / "latest.md").write_text(report)
    # Written whatever the outcome; governance accepts it only if it passed.
    bias_report_path(artifact).write_text(bias.model_dump_json(indent=2) + "\n")
    print(report)

    failures = [
        f"{a.script}: {a.wrong_but_confident} confident errors"
        for a in accuracy
        if a.wrong_but_confident
    ]
    if not bias.passes_four_fifths:
        failures.append(f"four-fifths ratio {bias.four_fifths_ratio:.2f} < {FOUR_FIFTHS}")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
