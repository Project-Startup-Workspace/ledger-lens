"""Firestore and Cloud Storage adapters against the official emulators.

Start them with `make emulators` (Docker). Skipped when they are not running.
"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from ledger_lens.audit_trail.chain import verify_chain
from ledger_lens.shared.schemas import Applicant, Consent, CreditFile, LoanRequest
from ledger_lens.shared.storage import ConcurrentUpdateError

pytestmark = pytest.mark.integration

FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
STORAGE = os.environ.get("STORAGE_EMULATOR_HOST")
needs_firestore = pytest.mark.skipif(not FIRESTORE, reason="FIRESTORE_EMULATOR_HOST not set")
needs_storage = pytest.mark.skipif(not STORAGE, reason="STORAGE_EMULATOR_HOST not set")
PROJECT = "ledger-lens-test"


def make_case() -> CreditFile:
    return CreditFile(
        case_id=f"case_{uuid.uuid4().hex[:12]}",
        jurisdiction="lk",
        applicant=Applicant(
            full_name="A",
            date_of_birth="1990-01-01",
            national_id="1",
            phone="1",
            business_name="B",
            business_type="shop",
            years_in_business=3,
        ),
        loan=LoanRequest(
            amount=Decimal(1000), currency="LKR", tenor_months=6, annual_rate_pct=20, purpose="x"
        ),
        consent=Consent(given=True),
    )


@needs_firestore
def test_firestore_case_repository_round_trip_and_conflicts() -> None:
    from ledger_lens.shared.storage import FirestoreCaseRepository

    repository = FirestoreCaseRepository(PROJECT)
    case = make_case()
    repository.save(case)
    assert case.revision == 1
    loaded = repository.get(case.case_id)
    assert loaded == case
    stale = repository.get(case.case_id)
    assert loaded and stale
    loaded.status = "assessed"  # type: ignore[assignment]
    repository.save(loaded)
    with pytest.raises(ConcurrentUpdateError):
        repository.save(stale)
    assert case.case_id in {c.case_id for c in repository.list(200)}
    assert repository.get("case_missing") is None


@needs_firestore
def test_firestore_lists_most_recently_updated_first() -> None:
    from ledger_lens.shared.storage import FirestoreCaseRepository

    repository = FirestoreCaseRepository(PROJECT, collection=f"cases_{uuid.uuid4().hex[:6]}")
    first, second = make_case(), make_case()
    repository.save(first)
    repository.save(second)
    repository.save(first)  # updated again, so it is now the most recent
    assert [c.case_id for c in repository.list(2)] == [first.case_id, second.case_id]


@needs_firestore
def test_firestore_audit_store_never_forks_under_concurrent_writers() -> None:
    from ledger_lens.audit_trail.stores import FirestoreAuditStore

    case_id = f"case_{uuid.uuid4().hex[:12]}"
    stores = [FirestoreAuditStore(PROJECT), FirestoreAuditStore(PROJECT)]

    def write(store: FirestoreAuditStore, n: int) -> None:
        for i in range(n):
            store.append(case_id, "step", "system", {"i": i, "phone": "0771234567"})

    threads = [threading.Thread(target=write, args=(s, 6)) for s in stores]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = stores[0].events(case_id)
    assert [e.seq for e in events] == list(range(12))
    assert verify_chain(events).valid
    assert all(e.payload["phone"] == "[phone]" for e in events)


@needs_storage
def test_gcs_blob_store_round_trip() -> None:
    from google.cloud import storage

    from ledger_lens.shared.storage import GcsBlobStore

    bucket = f"ll-test-{uuid.uuid4().hex[:8]}"
    storage.Client(project=PROJECT).create_bucket(bucket)
    store = GcsBlobStore(bucket)
    store.put("case_1/ev_1", b"\x89PNG data", "image/png")
    assert store.get("case_1/ev_1") == b"\x89PNG data"
    with pytest.raises(ValueError):
        store.put("../escape", b"x", "text/plain")
    assert store.find("case_1/ev_1") == b"\x89PNG data"
    assert store.find("case_1/missing") is None


@needs_firestore
def test_firestore_call_budget_is_shared_and_never_overspent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ledger_lens.shared import usage
    from ledger_lens.shared.usage import FirestoreCallBudget, ModelBudgetExceededError

    # A unique day keeps this run's counter apart from earlier runs on the same emulator.
    day = f"test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(usage, "_today", lambda: day)
    budgets = [FirestoreCallBudget(PROJECT, limit=8), FirestoreCallBudget(PROJECT, limit=8)]

    def take(i: int) -> bool:
        try:
            budgets[i % 2].take()
            return True
        except ModelBudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        granted = list(pool.map(take, range(20)))
    assert 0 < granted.count(True) <= 8  # contention may refuse early; never overspends
    # Refused calls handed their slots back, so the count is exactly what was granted.
    stored = budgets[0]._client.collection("usage").document(f"model-calls-{day}").get()
    assert stored.get("calls") == granted.count(True)

    # Without contention the whole allowance is usable.
    monkeypatch.setattr(usage, "_today", lambda: f"{day}-quiet")
    assert [take(i) for i in range(10)] == [True] * 8 + [False] * 2
