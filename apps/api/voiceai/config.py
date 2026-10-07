"""Application settings from environment variables and `.env`.

Spec: /architecture/deployment.md, /architecture/llm-gateway.md, /architecture/knowledge.md
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent  # apps/api
REPO_DIR = API_DIR.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite+aiosqlite:///{(API_DIR / 'data' / 'voiceai.db').as_posix()}"
    specs_dir: Path = REPO_DIR / "specs"
    web_dist_dir: Path = API_DIR.parent / "web" / "out"
    models_config: Path = API_DIR / "config" / "models.yaml"
    auto_seed: bool = True
    jobs_enabled: bool = True
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    deepgram_api_key: str | None = None
    llm_fake: bool = False
    # per-role model overrides (/architecture/llm-gateway.md, LG-06/LG-07); a real env var of the same name wins in the gateway
    llm_role_realtime: str | None = None
    llm_role_analysis: str | None = None
    llm_role_drafting: str | None = None
    llm_role_simulator: str | None = None
    llm_role_judge: str | None = None
    llm_role_turn: str | None = None

    embeddings_provider: str = "fastembed"  # fastembed | hash
    fastembed_cache: Path = API_DIR / ".cache" / "fastembed"
    kn_min_score: float | None = None  # default depends on embedder
    fl_cluster_threshold: float | None = None  # default depends on embedder
    fl_min_cluster_size: int = 5

    human_cost_per_call: float = 9.50
    ai_cost_per_call: float = 1.20

    ev_max_cluster_cases: int = 6
    ev_concurrency: int = 4

    voice_vad_stop_secs: float = 0.2
    deepgram_stt_model: str = "nova-3"

    @property
    def min_score(self) -> float:
        if self.kn_min_score is not None:
            return self.kn_min_score
        return 0.60 if self.embeddings_provider == "fastembed" else 0.15

    @property
    def cluster_threshold(self) -> float:
        if self.fl_cluster_threshold is not None:
            return self.fl_cluster_threshold
        return 0.80 if self.embeddings_provider == "fastembed" else 0.35

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
