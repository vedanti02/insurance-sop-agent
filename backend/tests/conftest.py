import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_MODE", "stub")

from app.blackboard import Blackboard  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.data import load_store  # noqa: E402
from app.perceive import Perception, ScriptedPerceiver  # noqa: E402
from app.policy import load_policy  # noqa: E402
from app.respond import StubResponder  # noqa: E402
from app.session import Session  # noqa: E402
from app.tools import ToolCtx  # noqa: E402
from app import verticals  # noqa: E402


@pytest.fixture(scope="session")
def store():
    return load_store()


@pytest.fixture(scope="session")
def policy():
    return load_policy("insurance_claims_v1")


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def make_session(store, policy, settings):
    """Build a session driven by scripted perceptions and the stub responder (zero LLM calls)."""
    def _make(script: list[Perception], consent_scenario: str = "default") -> Session:
        bb = Blackboard(session_id="test", vertical="insurance_claims_v1")
        bb.post_process.consent.scenario = consent_scenario
        ctx = ToolCtx(bb=bb, store=store, policy=policy, settings=settings, vertical=verticals.get("insurance_claims_v1"))
        return Session(ctx=ctx, perceiver=ScriptedPerceiver(script), responder=StubResponder())
    return _make


@pytest.fixture
def make_ctx(store, policy, settings):
    def _make(bb: Blackboard) -> ToolCtx:
        return ToolCtx(bb=bb, store=store, policy=policy, settings=settings, vertical=verticals.get("insurance_claims_v1"))
    return _make


def P(**kw) -> Perception:
    """Shorthand for building perceptions in tests."""
    from app.blackboard import CaseHints
    from app.perceive import IdentityCandidates
    ic = {k: kw.pop(k) for k in ("full_name", "dob", "id_last4", "phone", "email", "policy_number") if k in kw}
    hints = {k: kw.pop(k) for k in ("case_type", "status", "period", "case_id", "merchant", "amount") if k in kw}
    return Perception(identity_candidates=IdentityCandidates(**ic), case_hints=CaseHints(**hints), **kw)


MARGARET = dict(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472", policy_number="POL-9921")
