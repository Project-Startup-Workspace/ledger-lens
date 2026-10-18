"""A daily cap on paid model calls, shared by every instance, so a leaked sign-in or a
runaway script cannot run up an unbounded Gemini bill.

The count resets at midnight UTC. Each logical call counts once, so with LL_LLM_RETRIES=1 a
call that fails transiently can be billed twice.
"""

import fcntl
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ledger_lens.shared.config import Backend, LlmProvider, Settings
from ledger_lens.shared.llm import Attachment, LlmClient, LlmUnavailableError

T = TypeVar("T", bound=BaseModel)


class ModelBudgetExceededError(LlmUnavailableError):
    """Today's model-call budget is spent. Never replaced by a fallback: the officer is
    told, so a template is not saved silently in place of the model's explanation."""


class CallBudget(Protocol):
    def take(self) -> None:
        """Count one call, or raise ModelBudgetExceededError if none are left today."""
        ...

    def used(self) -> int:
        """Calls counted so far today."""
        ...


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _exceeded(limit: int) -> ModelBudgetExceededError:
    return ModelBudgetExceededError(
        f"today's limit of {limit} model calls is reached; it resets at midnight UTC"
    )


UNCAPPED = 10**12
Limit = int | Callable[[], int]  # a callable is read on every call, so it can change live


def _read(limit: Limit) -> int:
    return limit() if callable(limit) else limit


class LocalCallBudget:
    """A counter file under the data directory, locked so parallel page reads agree."""

    def __init__(self, path: Path, limit: Limit) -> None:
        self._path = path
        self._limit = limit
        path.parent.mkdir(parents=True, exist_ok=True)

    def used(self) -> int:
        state = json.loads(self._path.read_text()) if self._path.exists() else {}
        return int(state.get("calls", 0)) if state.get("day") == _today() else 0

    def take(self) -> None:
        limit = _read(self._limit)
        with self._path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            day = _today()
            state = json.loads(self._path.read_text()) if self._path.exists() else {}
            used = state.get("calls", 0) if state.get("day") == day else 0
            if used >= limit:
                raise _exceeded(limit)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": day, "calls": used + 1}))
            tmp.replace(self._path)  # atomic, so a crash never leaves an unreadable count


class FirestoreCallBudget:
    """One document per day in `usage/`, bumped with an atomic increment.

    A transaction would lock one hot document against the parallel page reads. Instead
    each call increments, then reads the total back: every increment gets its own
    position in the count, so at most `limit` calls ever see a total within the limit.
    Refused calls hand their slot back, so near the limit a call can be refused that
    would have fitted, but the budget is never overspent.
    """

    def __init__(self, project: str | None, limit: Limit) -> None:
        import google.cloud.firestore as firestore

        self._increment = firestore.Increment
        self._client = firestore.Client(project=project)
        self._limit = limit

    def _ref(self) -> Any:
        return self._client.collection("usage").document(f"model-calls-{_today()}")

    def used(self) -> int:
        snapshot = self._ref().get()
        return int(snapshot.get("calls") or 0) if snapshot.exists else 0

    def take(self) -> None:
        from google.api_core.exceptions import GoogleAPICallError

        limit = _read(self._limit)
        ref = self._ref()
        try:
            ref.set({"calls": self._increment(1)}, merge=True)
            if (ref.get().get("calls") or 0) <= limit:
                return
            # Hand the refused slot back. A granted call never returns its slot, so every
            # grant still saw a total that included all grants before it.
            ref.set({"calls": self._increment(-1)}, merge=True)
        except GoogleAPICallError as exc:
            # Fail closed: an uncounted call is an uncapped one.
            raise LlmUnavailableError(f"could not check the model-call budget: {exc}") from exc
        raise _exceeded(limit)


class MeteredLlm:
    """Takes from the budget before every call it passes to the real client."""

    def __init__(self, inner: LlmClient, budget: CallBudget) -> None:
        self._inner = inner
        self._budget = budget

    @property
    def budget(self) -> CallBudget:
        return self._budget

    def generate(
        self,
        *,
        task: str,
        model: str,
        system: str,
        prompt: str,
        schema: type[T],
        attachments: Sequence[Attachment] = (),
    ) -> T:
        self._budget.take()
        return self._inner.generate(
            task=task,
            model=model,
            system=system,
            prompt=prompt,
            schema=schema,
            attachments=attachments,
        )

    def speak(self, *, text: str, language: str) -> bytes:
        self._budget.take()
        return self._inner.speak(text=text, language=language)


def metered(llm: LlmClient, settings: Settings, limit: Limit | None = None) -> LlmClient:
    """Wrap `llm` in the daily budget. Offline replays cost nothing, and 0 means no cap.
    `limit` replaces the deployment's setting, e.g. with the platform admin's."""
    limit = settings.daily_model_calls if limit is None else limit
    if settings.llm_provider is LlmProvider.OFFLINE or limit == 0:
        return llm
    if callable(limit):
        live = limit
        limit = lambda: live() or UNCAPPED  # noqa: E731 - 0 set live also means no cap
    budget: CallBudget
    if settings.storage_backend is Backend.GCP:
        budget = FirestoreCallBudget(settings.gcp_project, limit)
    else:
        budget = LocalCallBudget(settings.data_dir / "usage" / "model-calls.json", limit)
    return MeteredLlm(llm, budget)
