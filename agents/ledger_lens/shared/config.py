"""Runtime configuration, read once from environment variables.

Model names, regions and thresholds live here rather than in agent code because
they change more often than the logic does (see the Gemini 1.5 retirement).
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class LlmProvider(StrEnum):
    """Where Gemini calls go."""

    OFFLINE = "offline"  # recorded fixtures only; no network, used in tests and local demos
    VERTEX = "vertex"  # Gemini Enterprise Agent Platform, authenticated with ADC
    GEMINI_API = "gemini_api"  # Gemini Developer API, authenticated with an API key


class Backend(StrEnum):
    """Whether a capability runs on local substitutes or on Google Cloud."""

    LOCAL = "local"
    GCP = "gcp"


class Settings(BaseSettings):
    """All tunable settings. Every field maps to an `LL_`-prefixed env var."""

    model_config = SettingsConfigDict(
        env_prefix="LL_", env_file=(REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    environment: str = "local"
    log_level: str = "INFO"

    # Gemini
    llm_provider: LlmProvider = LlmProvider.OFFLINE
    gemini_api_key: SecretStr | None = None
    gcp_project: str | None = None
    gcp_region: str = "asia-southeast1"
    genai_location: str = "global"  # some newer models are served only from global endpoints
    model_extract: str = "gemini-3.8-flash"
    model_reason: str = "gemini-3.1-pro"
    model_tts: str = "gemini-3.8-flash-tts"
    tts_voice: str = "Kore"
    llm_timeout_s: float = 90.0
    llm_retries: int = 1

    # Backends for storage, risk scoring, safety screening and regulation retrieval
    storage_backend: Backend = Backend.LOCAL
    risk_backend: Backend = Backend.LOCAL
    safety_backend: Backend = Backend.LOCAL
    retrieval_backend: Backend = Backend.LOCAL
    data_dir: Path = REPO_ROOT / ".data"
    evidence_bucket: str | None = None
    audit_bucket: str | None = None
    bq_dataset: str = "ledger_lens"
    model_armor_template: str | None = None
    rag_corpus: str | None = None

    # Domain thresholds
    rule_packs_dir: Path = REPO_ROOT / "rule-packs"
    fixtures_dir: Path = REPO_ROOT / "demo-data" / "fixtures"
    min_extraction_confidence: float = Field(default=0.6, ge=0, le=1)
    consistency_tolerance: float = Field(default=0.35, ge=0, le=1)

    # Lender profile used by licensing checks; JSON object of jurisdiction -> licence number
    lender_name: str = "Demo Microfinance Ltd (synthetic)"
    lender_licences: dict[str, str] = {"lk": "MCRA-DEMO-0001", "sg": "MAS-DEMO-0001"}

    # Feature flags for work that must not break the demo
    enable_tts: bool = True
    enable_live_voice: bool = False

    # Web origin allowed to call the API from a browser
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loading them on first use."""
    return Settings()
