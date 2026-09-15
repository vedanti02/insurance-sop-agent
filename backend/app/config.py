"""Runtime settings. Everything comes from the environment; nothing here is secret-bearing code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR", PROJECT_DIR / "fixtures"))
VERTICALS_DIR = Path(os.environ.get("VERTICALS_DIR", PROJECT_DIR / "verticals"))


@dataclass(frozen=True)
class Settings:
    llm_mode: str            # "live" | "stub"
    llm_provider: str        # "openai"
    llm_api_key: str | None
    llm_base_url: str | None
    perceive_model: str
    respond_model: str
    demo_today: date         # the SOP's notion of "today" (fixture deadlines are in early 2026)
    consent_scenario: str    # key into consent_scenarios.json
    max_model_calls_per_turn: int
    vertical: str


def load_settings() -> Settings:
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    mode = os.environ.get("LLM_MODE", "live" if key else "stub")
    if mode == "live" and not key:
        raise RuntimeError("LLM_API_KEY (or OPENAI_API_KEY) is required when LLM_MODE=live")
    return Settings(
        llm_mode=mode,
        llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
        llm_api_key=key,
        llm_base_url=os.environ.get("LLM_BASE_URL") or None,
        perceive_model=os.environ.get("PERCEIVE_MODEL", "gpt-4.1-mini"),
        respond_model=os.environ.get("RESPOND_MODEL", "gpt-4.1"),
        demo_today=date.fromisoformat(os.environ.get("DEMO_TODAY", "2026-03-01")),
        consent_scenario=os.environ.get("CONSENT_SCENARIO", "default"),
        max_model_calls_per_turn=int(os.environ.get("MAX_MODEL_CALLS_PER_TURN", "3")),
        vertical=os.environ.get("VERTICAL", "insurance_claims_v1"),
    )
