"""One narrow gateway to Gemini, so every call has a schema, a timeout and one retry.

`OfflineLlm` replays recorded responses from `demo-data/fixtures/`, which keeps tests
and local demos free of network calls and credentials.
"""

import hashlib
import io
import json
import logging
import time
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ledger_lens.shared.config import LlmProvider, Settings

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
log = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24_000  # Gemini TTS returns 16-bit mono PCM at 24 kHz


class LlmError(RuntimeError):
    """A model call failed after its retry, or returned output that broke its schema."""


class LlmUnavailableError(LlmError):
    """No model can answer this request in the current mode (e.g. offline, no fixture)."""


@dataclass(frozen=True)
class Attachment:
    data: bytes
    mime_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class LlmClient(Protocol):
    """What agents need from a model. Implementations must enforce `schema`.

    `schema` must be a flat wire schema (no dict fields): the Gemini Developer API
    rejects `additionalProperties`, so shared contracts are never sent as-is.
    """

    def generate(
        self,
        *,
        task: str,
        model: str,
        system: str,
        prompt: str,
        schema: type[T],
        attachments: Sequence[Attachment] = (),
    ) -> T: ...

    def speak(self, *, text: str, language: str) -> bytes:
        """Return WAV audio of `text` read aloud."""
        ...


def fixture_key(task: str, attachments: Sequence[Attachment], prompt: str) -> str:
    """Name of the recorded response for a call.

    Calls with attachments are keyed on the attachments alone, so editing a prompt does
    not invalidate every recorded page; text-only calls are keyed on the prompt.
    """
    digest = hashlib.sha256()
    for item in attachments:
        digest.update(item.sha256.encode())
    if not attachments:
        digest.update(prompt.encode())
    return f"{task}-{digest.hexdigest()[:16]}"


class OfflineLlm:
    """Replays recorded JSON responses; raises `LlmUnavailableError` when none exists."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir

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
        path = self._dir / f"{fixture_key(task, attachments, prompt)}.json"
        if not path.exists():
            raise LlmUnavailableError(f"no offline fixture for {task} ({path.name})")
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise LlmError(f"fixture {path.name} does not match {schema.__name__}") from exc

    def speak(self, *, text: str, language: str) -> bytes:
        raise LlmUnavailableError("speech needs a Gemini provider")


class GeminiLlm:
    """Calls Gemini through the google-genai SDK on Vertex AI or the Developer API."""

    def __init__(self, settings: Settings) -> None:
        from google import genai  # imported lazily so offline mode needs no SDK setup
        from google.genai import types

        self._types = types
        self._settings = settings
        http = types.HttpOptions(timeout=int(settings.llm_timeout_s * 1000))
        if settings.llm_provider is LlmProvider.VERTEX:
            self._client = genai.Client(
                vertexai=True,
                project=settings.gcp_project,
                location=settings.genai_location,
                http_options=http,
            )
        else:
            key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            self._client = genai.Client(api_key=key, http_options=http)

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
        types = self._types
        if "additionalProperties" in json.dumps(schema.model_json_schema()):
            raise TypeError(f"{schema.__name__} has dict fields; send a flat wire schema")
        contents: list[object] = [
            types.Part.from_bytes(data=a.data, mime_type=a.mime_type) for a in attachments
        ]
        contents.append(prompt)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
        )
        return self._with_retry(
            task,
            lambda: schema.model_validate_json(
                self._client.models.generate_content(
                    model=model, contents=contents, config=config
                ).text
                or ""
            ),
        )

    def speak(self, *, text: str, language: str) -> bytes:
        types = self._types
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code=language,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._settings.tts_voice
                    )
                ),
            ),
        )

        def call() -> bytes:
            response = self._client.models.generate_content(
                model=self._settings.model_tts, contents=text, config=config
            )
            content = response.candidates[0].content if response.candidates else None
            parts = content.parts if content else None
            pcm = parts[0].inline_data.data if parts and parts[0].inline_data else None
            if not pcm:
                raise LlmError("TTS response held no audio")
            return pcm_to_wav(pcm)

        return self._with_retry("tts", call)

    def _with_retry(self, task: str, call: Callable[[], R]) -> R:
        attempts = self._settings.llm_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return call()
            except Exception as exc:
                retry = _is_transient(exc) and attempt < attempts
                log.warning(
                    "llm call failed", extra={"task": task, "attempt": attempt, "retry": retry}
                )
                if not retry:
                    raise LlmError(f"{task} failed after {attempt} attempt(s): {exc}") from exc
                time.sleep(1.5 * attempt)
        raise AssertionError("unreachable: attempts is at least 1")


def _is_transient(exc: Exception) -> bool:
    """Retry timeouts, rate limits, server errors and malformed output; not bad requests."""
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    if isinstance(exc, ValidationError):
        return True  # sampling can produce invalid JSON once and valid JSON the next time
    return isinstance(exc, TimeoutError | ConnectionError) or "Timeout" in type(exc).__name__


def pcm_to_wav(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container that browsers can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def build_llm(settings: Settings) -> LlmClient:
    """Return the client for the configured provider."""
    if settings.llm_provider is LlmProvider.OFFLINE:
        return OfflineLlm(settings.fixtures_dir)
    return GeminiLlm(settings)
