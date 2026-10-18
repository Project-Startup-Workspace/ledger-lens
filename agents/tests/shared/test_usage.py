"""The daily model-call budget; saved speech and translations keep replays free."""

import dataclasses
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger_lens.api.app import create_app
from ledger_lens.coordinator import Coordinator, build_services
from ledger_lens.demo import open_demo_case
from ledger_lens.explain.agent import ExplainAgent
from ledger_lens.explain.schemas import WireExplanation
from ledger_lens.shared import usage
from ledger_lens.shared.config import LlmProvider, Settings
from ledger_lens.shared.llm import OfflineLlm
from ledger_lens.shared.safety import HeuristicScreen
from ledger_lens.shared.usage import (
    LocalCallBudget,
    MeteredLlm,
    ModelBudgetExceededError,
    metered,
)


class CountingSpeaker:
    def __init__(self) -> None:
        self.calls = 0

    def speak(self, text: str, language: str) -> bytes:
        self.calls += 1
        return f"wav:{language}:{len(text)}".encode()


def test_budget_refuses_once_the_daily_limit_is_spent(tmp_path: Path) -> None:
    budget = LocalCallBudget(tmp_path / "calls.json", limit=3)
    for _ in range(3):
        budget.take()
    with pytest.raises(ModelBudgetExceededError, match="limit of 3"):
        budget.take()


def test_budget_resets_on_a_new_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    budget = LocalCallBudget(tmp_path / "calls.json", limit=1)
    monkeypatch.setattr(usage, "_today", lambda: "2026-10-17")
    budget.take()
    monkeypatch.setattr(usage, "_today", lambda: "2026-10-18")
    budget.take()  # a fresh day, a fresh allowance


def test_budget_holds_under_parallel_page_reads(tmp_path: Path) -> None:
    budget = LocalCallBudget(tmp_path / "calls.json", limit=10)

    def take() -> bool:
        try:
            budget.take()
            return True
        except ModelBudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        granted = list(pool.map(lambda _: take(), range(25)))
    assert granted.count(True) == 10


def test_offline_or_uncapped_clients_are_not_metered(settings: Settings) -> None:
    offline = OfflineLlm(settings.fixtures_dir)
    assert metered(offline, settings) is offline
    vertex_uncapped = settings.model_copy(
        update={"llm_provider": LlmProvider.VERTEX, "daily_model_calls": 0}
    )
    assert metered(offline, vertex_uncapped) is offline
    vertex = settings.model_copy(update={"llm_provider": LlmProvider.VERTEX})
    assert isinstance(metered(offline, vertex), MeteredLlm)


def test_a_spent_budget_stops_the_call_before_it_reaches_the_model(tmp_path: Path) -> None:
    class Unreachable:
        def generate(self, **_: object) -> None:
            raise AssertionError("the model must not be called")

        def speak(self, **_: object) -> bytes:
            raise AssertionError("the model must not be called")

    llm = MeteredLlm(Unreachable(), LocalCallBudget(tmp_path / "calls.json", limit=0))  # type: ignore[arg-type]
    with pytest.raises(ModelBudgetExceededError):
        llm.speak(text="hello", language="en-US")


def test_api_reports_a_spent_budget_as_429(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def spent(*_: object) -> bytes:
        raise ModelBudgetExceededError("today's limit of 300 model calls is reached")

    monkeypatch.setattr(Coordinator, "speech", spent)
    client = TestClient(create_app(settings))
    case_id = client.post("/demo-cases/synthetic-grocer-kandy").json()["case_id"]
    response = client.get(f"/cases/{case_id}/explanation/audio")
    assert response.status_code == 429
    assert "limit of 300" in response.json()["detail"]


def test_speech_is_saved_so_replays_cost_no_model_call(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id, "officer-1")
    speaker = CountingSpeaker()
    coordinator._s = dataclasses.replace(coordinator._s, explain=speaker)

    first = coordinator.speech(case.case_id)
    assert coordinator.speech(case.case_id) == first
    assert speaker.calls == 1

    # A different explanation is different audio, so it is spoken afresh.
    stored = coordinator._s.cases.get(case.case_id)
    assert stored and stored.explanation
    stored.explanation.borrower_text += " Thank you."
    coordinator._s.cases.save(stored)
    assert coordinator.speech(case.case_id) != first
    assert speaker.calls == 2


def test_concurrent_first_plays_pay_for_speech_once(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id, "officer-1")
    speaker = CountingSpeaker()
    coordinator._s = dataclasses.replace(coordinator._s, explain=speaker)

    with ThreadPoolExecutor(max_workers=4) as pool:
        plays = list(pool.map(lambda _: coordinator.speech(case.case_id), range(4)))
    assert len(set(plays)) == 1
    assert speaker.calls == 1


def test_paid_audio_is_served_even_when_saving_it_fails(settings: Settings) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id, "officer-1")

    class FailingPut:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def find(self, key: str) -> bytes | None:
            return None

        def put(self, *_: object) -> None:
            raise OSError("bucket unavailable")

    coordinator._s = dataclasses.replace(
        coordinator._s, explain=CountingSpeaker(), blobs=FailingPut(coordinator._s.blobs)
    )
    assert coordinator.speech(case.case_id).startswith(b"wav:")


def test_a_spent_budget_is_reported_not_replaced_by_the_template(
    settings: Settings, tmp_path: Path
) -> None:
    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    case = coordinator.assess(case.case_id, "officer-1")
    spent = MeteredLlm(
        OfflineLlm(settings.fixtures_dir), LocalCallBudget(tmp_path / "calls.json", limit=0)
    )
    with pytest.raises(ModelBudgetExceededError):
        ExplainAgent(spent, HeuristicScreen(), settings).explain(case, "si")


def test_switching_back_to_a_language_costs_no_model_call(settings: Settings) -> None:
    class Writer:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, **_: object) -> WireExplanation:
            self.calls += 1
            return WireExplanation(borrower_text="Thank you.", english_text="Thank you.")

    coordinator = Coordinator(build_services(settings))
    case = open_demo_case(coordinator, "synthetic-grocer-kandy", "officer-1")
    coordinator.assess(case.case_id, "officer-1")
    writer = Writer()
    online = settings.model_copy(update={"llm_provider": LlmProvider.VERTEX})
    coordinator._s = dataclasses.replace(
        coordinator._s,
        explain=ExplainAgent(writer, HeuristicScreen(), online),  # type: ignore[arg-type]
    )
    for language in ("ta", "en", "ta", "en", "id"):
        shown = coordinator.explain_in(case.case_id, language, "officer-1")
        assert shown.borrower_language == language
    assert writer.calls == 3
    stored = coordinator.get(case.case_id)
    assert set(stored.translations) == {"ta", "en", "id"}
