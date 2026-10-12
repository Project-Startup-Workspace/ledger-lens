"""Opens the synthetic demo cases in demo-data/ through the normal coordinator path."""

import json
import mimetypes

from ledger_lens.coordinator import Coordinator
from ledger_lens.shared.config import REPO_ROOT
from ledger_lens.shared.schemas import Applicant, Consent, CreditFile, EvidenceKind, LoanRequest

DEMO_DIR = REPO_ROOT / "demo-data"


def demo_cases() -> list[str]:
    return sorted(p.parent.name for p in DEMO_DIR.glob("synthetic-*/case.json"))


def open_demo_case(coordinator: Coordinator, slug: str, actor: str) -> CreditFile:
    """Create the case and upload its notebook pages and statement, ready to assess."""
    if slug not in demo_cases():
        raise KeyError(slug)
    folder = DEMO_DIR / slug
    spec = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    case = coordinator.create_case(
        applicant=Applicant.model_validate(spec["applicant"]),
        loan=LoanRequest.model_validate(spec["loan"]),
        consent=Consent(given=True, method="digital"),
        jurisdiction=spec["jurisdiction"],
        actor=actor,
    )
    files = [(p, EvidenceKind.NOTEBOOK) for p in sorted(folder.glob("notebook-p*.png"))]
    if (wallet := folder / "wallet-statement.csv").exists():
        files.append((wallet, EvidenceKind.WALLET_STATEMENT))
    for path, kind in files:
        coordinator.add_evidence(
            case.case_id,
            kind=kind,
            filename=path.name,
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            data=path.read_bytes(),
            actor=actor,
        )
    return coordinator.get(case.case_id)
