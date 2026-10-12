"""Shared fixtures: settings pointed at the repo's demo data, offline model."""

from pathlib import Path

import pytest

from ledger_lens.shared.config import REPO_ROOT, LlmProvider, Settings

DEMO = REPO_ROOT / "demo-data"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider=LlmProvider.OFFLINE,
        data_dir=tmp_path / "data",
        fixtures_dir=DEMO / "fixtures",
        _env_file=None,  # type: ignore[call-arg]
    )
