"""Offline replay and audio packaging in the LLM gateway."""

import io
import wave
from pathlib import Path

import pytest
from pydantic import BaseModel

from ledger_lens.shared.llm import (
    Attachment,
    LlmError,
    LlmUnavailableError,
    OfflineLlm,
    fixture_key,
    pcm_to_wav,
)


class Greeting(BaseModel):
    text: str


def _call(llm: OfflineLlm, attachment: Attachment) -> Greeting:
    return llm.generate(
        task="greet", model="m", system="s", prompt="p", schema=Greeting, attachments=[attachment]
    )


def test_offline_replays_fixture_matching_attachment(tmp_path: Path) -> None:
    attachment = Attachment(b"page", "image/png")
    (tmp_path / f"{fixture_key('greet', [attachment], 'p')}.json").write_text('{"text": "hi"}')
    assert _call(OfflineLlm(tmp_path), attachment).text == "hi"


def test_offline_without_fixture_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(LlmUnavailableError):
        _call(OfflineLlm(tmp_path), Attachment(b"other", "image/png"))


def test_offline_rejects_fixture_that_breaks_schema(tmp_path: Path) -> None:
    attachment = Attachment(b"page", "image/png")
    (tmp_path / f"{fixture_key('greet', [attachment], 'p')}.json").write_text('{"txt": 1}')
    with pytest.raises(LlmError):
        _call(OfflineLlm(tmp_path), attachment)


def test_pcm_to_wav_produces_playable_header() -> None:
    with wave.open(io.BytesIO(pcm_to_wav(b"\x00\x00" * 240))) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getnframes()) == (1, 24_000, 240)
