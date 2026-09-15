"""Server-side sessions keyed by id. Perceiver/responder pairs are built per session so a
caller-supplied API key never leaks across sessions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date

from . import verticals
from .blackboard import Blackboard
from .config import Settings
from .perceive import HeuristicPerceiver, Perceiver
from .policy import Policy, load_policy
from .respond import Responder, StubResponder
from .tools import ToolCtx
from .turn import TurnResult, run_turn
from .validate import Validator


@dataclass
class Session:
    ctx: ToolCtx
    perceiver: Perceiver
    responder: Responder
    validators: list[Validator] = field(default_factory=list)
    mode: str = "stub"

    @property
    def bb(self) -> Blackboard:
        return self.ctx.bb

    def turn(self, text: str) -> TurnResult:
        return run_turn(self.ctx, text, self.perceiver, self.responder, self.validators)


class SessionManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stores: dict[str, object] = {}
        self.policies: dict[str, Policy] = {}
        self.sessions: dict[str, Session] = {}

    def policy(self, vertical: str) -> Policy:
        if vertical not in self.policies:
            self.policies[vertical] = load_policy(vertical)
        return self.policies[vertical]

    def store(self, vertical: str):
        if vertical not in self.stores:
            self.stores[vertical] = verticals.get(vertical).load_store()
        return self.stores[vertical]

    def create(self, vertical: str | None = None, consent_scenario: str | None = None,
               api_key: str | None = None, demo_today: str | None = None) -> Session:
        s = self.settings
        if api_key:
            s = replace(s, llm_api_key=api_key, llm_mode="live")
        if demo_today:
            s = replace(s, demo_today=date.fromisoformat(demo_today))
        vertical = vertical or s.vertical
        bb = Blackboard(session_id=uuid.uuid4().hex[:12], vertical=vertical)
        bb.post_process.consent.scenario = consent_scenario or s.consent_scenario
        policy = self.policy(vertical)
        bb.phase = policy.initial_phase
        ctx = ToolCtx(bb=bb, store=self.store(vertical), policy=policy, settings=s, vertical=verticals.get(vertical))
        perceiver, responder, validators, mode = self._build(ctx, s)
        sess = Session(ctx=ctx, perceiver=perceiver, responder=responder, validators=validators, mode=mode)
        self.sessions[bb.session_id] = sess
        return sess

    def _build(self, ctx: ToolCtx, s: Settings):
        from .validate import default_validators
        if s.llm_mode == "live" and s.llm_api_key:
            from .llm import LLMPerceiver, LLMResponder, OpenAIClient
            client = OpenAIClient(s)
            return LLMPerceiver(client), LLMResponder(client), default_validators(), "live"
        return HeuristicPerceiver(), StubResponder(), default_validators(), "stub"

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None
