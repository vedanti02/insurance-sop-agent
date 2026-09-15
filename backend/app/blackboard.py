"""The blackboard: the single source of session state. The model writes facts into it via
perception; the harness reads predicates off it. Nothing from policyholders.json is stored here."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PII_KEYS = {"full_name", "dob", "id_last4", "phone", "email", "value", "policy_number", "rep_name"}


def mask_pii(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if k in PII_KEYS and obj[k] not in (None, "", False) else mask_pii(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_pii(v) for v in obj]
    return obj


class Message(BaseModel):
    role: Literal["caller", "agent"]
    text: str
    turn: int


class TraceEntry(BaseModel):
    turn: int
    kind: str  # perception | memory | tool | transition | directive | validator | safety | llm | info
    data: dict = Field(default_factory=dict)


class CaseHints(BaseModel):
    """Descriptors of which record the caller means. Verticals use the subset that fits them."""
    case_type: str | None = None
    status: str | None = None
    period: str | None = None
    case_id: str | None = None
    merchant: str | None = None
    amount: str | None = None

    def is_empty(self) -> bool:
        return not any(self.model_dump().values())

    def merged(self, other: "CaseHints") -> "CaseHints":
        return CaseHints(**{k: (getattr(other, k) or getattr(self, k)) for k in CaseHints.model_fields})


class Identity(BaseModel):
    caller_role: Literal["self", "representative"] | None = None
    rep_name: str | None = None
    rep_relationship: str | None = None
    rep_verified: bool = False
    resolved_party: str | None = None            # party_id only; never a fixture value
    candidates: dict[str, str] = Field(default_factory=dict)  # this turn's caller-supplied values; cleared after use
    verified_fields: list[str] = Field(default_factory=list)
    mismatched_fields_last_turn: list[str] = Field(default_factory=list)
    mismatched_turns: int = 0
    unknown_policy_attempts: int = 0
    locked: bool = False
    access_granted: bool = False                 # derived by verify.update_access; the only thing the gate reads


class IntentState(BaseModel):
    intent: str | None = None
    intent_turn: int | None = None
    case_hints: CaseHints = Field(default_factory=CaseHints)
    hints_turn: int | None = None
    candidate_cases: list[dict] = Field(default_factory=list)
    resolved_case: str | None = None
    resolved_turn: int | None = None
    handled: bool = False
    handled_cases: list[str] = Field(default_factory=list)
    no_claims: bool = False
    new_case_request: bool = False


class Control(BaseModel):
    scope_strikes: int = 0
    emotion: str = "neutral"
    refusal: bool = False
    persuasion_spent: int = 0
    escalation_reason: str | None = None
    wants_human: bool = False
    done: bool = False
    injection_suspected: bool = False
    pending: str | None = None                   # machine-readable name of the question last asked
    pending_options: list[str] = Field(default_factory=list)
    last_utterance: str = ""
    ungrounded_question: bool = False


class Consent(BaseModel):
    state: Literal["none", "pending", "approved", "denied"] = "none"
    polls: int = 0
    scenario: str = "default"


class PostProcess(BaseModel):
    summary: dict | None = None
    decision: Literal["send", "skip"] | None = None
    receipt: str | None = None
    consent: Consent = Field(default_factory=Consent)


class Blackboard(BaseModel):
    session_id: str
    vertical: str
    phase: str = "VERIFY_ID"
    turn: int = 0
    closed: bool = False
    identity: Identity = Field(default_factory=Identity)
    intent: IntentState = Field(default_factory=IntentState)
    documents: dict[str, str] = Field(default_factory=dict)   # doc name -> requested|alternative_offered|declined
    control: Control = Field(default_factory=Control)
    post_process: PostProcess = Field(default_factory=PostProcess)
    bundle: dict = Field(default_factory=dict)                 # facts the responder may state this turn
    history: list[Message] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)
    model_calls_this_turn: int = 0
    usage: dict = Field(default_factory=lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0})

    # --- helpers -----------------------------------------------------------------
    def log(self, kind: str, **data: Any) -> None:
        self.trace.append(TraceEntry(turn=self.turn, kind=kind, data=data))

    @property
    def verified_count(self) -> int:
        return len(self.identity.verified_fields)

    def recent(self, n: int = 6) -> list[Message]:
        return self.history[-n:]

    def public_view(self) -> dict:
        """What the UI sees. Caller-supplied PII is masked; fixture PII never enters the board."""
        d = self.model_dump(mode="json", exclude={"history", "trace", "bundle"})
        d["identity"]["candidates"] = {k: "***" for k in self.identity.candidates}
        d["verified_count"] = self.verified_count
        d["trace"] = [mask_pii(t.model_dump(mode="json")) for t in self.trace]
        d["history"] = [m.model_dump() for m in self.history]
        return d
