"""Environment configuration; all relative data paths are app-relative."""
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "data" / "deepnotes.sqlite3"
    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4o-mini"
    demo_mode: bool = False
    timeout: float = 45.0
    poll_seconds: float = 2.0
    max_attempts: int = 3
    retry_seconds: float = 10.0
    lease_seconds: float = 120.0

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        path = Path(os.getenv("DEEPNOTES_DB", "data/deepnotes.sqlite3"))
        if not path.is_absolute():
            path = ROOT / path
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        if not 1 <= timeout <= 120:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 120")
        return cls(
            db_path=path.resolve(),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            model=os.getenv("LLM_MODEL", "openai/gpt-4o-mini"),
            demo_mode=os.getenv("DEEPNOTES_DEMO", "false").lower() == "true",
            timeout=timeout,
            lease_seconds=max(120.0, timeout * 2 + 30),
        )
