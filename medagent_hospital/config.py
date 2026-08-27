"""Runtime configuration loaded from environment variables and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

def _load_dotenv(path: str | Path) -> None:
    """Load KEY=VALUE pairs; falls back to a tiny parser when python-dotenv is absent."""
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except ImportError:
        pass
    path = Path(path)
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Settings:
    llm_backend: str = "rule"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    huatuo_base_url: str = ""
    huatuo_model: str = "huatuo"
    database_url: str = ""
    redis_url: str = ""
    seed: int = 42
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        _load_dotenv(env_file or PROJECT_ROOT / ".env")
        return cls(
            llm_backend=os.getenv("LLM_BACKEND", "rule").strip().lower(),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            huatuo_base_url=os.getenv("HUATUO_BASE_URL", "").strip(),
            huatuo_model=os.getenv("HUATUO_MODEL", "huatuo").strip(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            redis_url=os.getenv("REDIS_URL", "").strip(),
            seed=int(os.getenv("SEED", "42")),
            data_dir=Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data")),
        )


def get_settings() -> Settings:
    return Settings.from_env()
