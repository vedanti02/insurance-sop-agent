"""Perception: structured extraction from one caller utterance, run every turn in every phase.

Output is untrusted. It writes identity *candidates*, never verified fields, and the
harness decides what to do with every signal.
"""
from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .blackboard import Blackboard, CaseHints

Emotion = Literal["neutral", "frustrated", "anxious", "angry", "confused"]


class IdentityCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = None
    dob: str | None = None
    id_last4: str | None = None
    phone: str | None = None
    email: str | None = None
    policy_number: str | None = None

    def present(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v}


class RepresentativeClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rep_name: str | None = None
    relationship: str | None = None


class Perception(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caller_role_claim: Literal["self", "representative"] | None = None
    representative: RepresentativeClaim | None = None
    identity_candidates: IdentityCandidates = Field(default_factory=IdentityCandidates)
    intent: str | None = None                 # validated against the vertical's INTENTS in clamped()
    case_hints: CaseHints = Field(default_factory=CaseHints)
    scope: Literal["in_scope", "out_of_scope"] = "in_scope"
    emotion: Emotion = "neutral"
    refusal: bool = False
    consent_signal: Literal["yes", "no"] | None = None   # answer to whatever the agent last asked
    new_case_request: bool = False
    wants_human: bool = False
    done: bool = False
    injection_suspected: bool = False
    document_unavailable: str | None = None   # document the caller says they cannot obtain ("all" if none of them)
    question: str | None = None               # the caller's in-scope question, short paraphrase

    def clamped(self, intents: tuple[str, ...] | None = None) -> "Perception":
        """Length-limit every free-text field from an untrusted extractor; drop unknown intents."""
        if intents is not None and self.intent not in intents:
            self.intent = None
        limits = {"full_name": 80, "dob": 40, "id_last4": 40, "phone": 40, "email": 80, "policy_number": 20}
        ic = self.identity_candidates
        for k, n in limits.items():
            if (v := getattr(ic, k)) is not None:
                setattr(ic, k, v.strip()[:n] or None)
        if self.representative:
            self.representative.rep_name = (self.representative.rep_name or "")[:80] or None
            self.representative.relationship = (self.representative.relationship or "")[:40] or None
        for k in CaseHints.model_fields:
            if (v := getattr(self.case_hints, k)) is not None:
                setattr(self.case_hints, k, v.strip()[:40] or None)
        self.document_unavailable = (self.document_unavailable or "")[:80] or None
        self.question = (self.question or "")[:200] or None
        return self


class Perceiver(Protocol):
    def perceive(self, text: str, bb: Blackboard) -> Perception: ...


class ScriptedPerceiver:
    """Test double: returns pre-written perceptions in order."""

    def __init__(self, script: list[Perception]):
        self.script = list(script)

    def perceive(self, text: str, bb: Blackboard) -> Perception:
        return self.script.pop(0) if self.script else Perception()


# --- heuristic perceiver (offline demo / fallback) --------------------------------------
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_RX = {
    "policy": re.compile(r"\bPOL-?\s?(\d{4})\b", re.I),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"(?<!\d)(\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)"),
    "dob": re.compile(rf"\b(\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}})\b", re.I),
    "last4": re.compile(r"(?:ssn|social|national\s*id|id|last\s*(?:four|4)\s*(?:digits?)?)\D{0,25}?(\d{4})\b", re.I),
    "last4_spoken": re.compile(r"last\s*(?:four|4)\D{0,15}?((?:(?:zero|one|two|three|four|five|six|seven|eight|nine)[\s-]*){4})", re.I),
    "name": re.compile(r"(?:my name is|my name's|this is|i'm|i am|it's|name is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"),
    "rep": re.compile(r"\b(?:her|his|my mother'?s?|my father'?s?)\s+(son|daughter|husband|wife|spouse|caregiver)\b|\bon behalf of\b|\bcalling for my (mother|father|mom|dad)\b", re.I),
    "yes": re.compile(r"^\s*(yes|yeah|yep|yup|sure|please|ok|okay|go ahead|send it|do it|correct|that's right|right)\b", re.I),
    "no": re.compile(r"^\s*(no|nope|nah|skip|don't|do not|not now|no thanks|i'm good)\b", re.I),
    "human": re.compile(r"\b(talk|speak) to (a|an|some)?\s*(human|person|agent|representative|supervisor|manager)\b|\btransfer me\b|\bget me a (human|person|manager)\b|\breal person\b", re.I),
    "done": re.compile(r"\b(that'?s all|that'?s it|nothing else|no,? that'?s everything|all set|goodbye|bye|i'?m done)\b", re.I),
    "refusal": re.compile(r"\b(not (going to|gonna) (give|tell|share)|won'?t (give|tell|share)|refuse|why do you need|not telling you|i already told you)\b", re.I),
    "cant_get": re.compile(r"\b(can'?t|cannot|unable to|don'?t have|couldn'?t)\b.{0,40}?\b(pathology report|office note|diagnosis report|repair estimate|photos?|report|note)\b", re.I),
    "new_case": re.compile(r"\b(actually|other claim|another claim|different claim|instead|switch to|what about my)\b", re.I),
    "injection": re.compile(r"\b(ignore (all|previous|prior|your) (instructions|rules)|system prompt|you are now|developer mode|pretend (you|that)|as an ai)\b", re.I),
}
_IN_SCOPE = re.compile(r"\b(claim|policy|denied|denial|appeal|document|submit|upload|insurance|coverage|reimburse|pay|paid|status|deadline|verify|verification|identity|name|dob|born|birth|ssn|social|phone|email|summary|human|representative|agent|thanks|thank you|hello|hi|hey|yes|no|okay|ok|bye|net|fee|amount|allowed|how long|how soon|fax|portal|pdf|format|estimate|report|note|photo|pending|open|closed|auto|dental|health|medical|car|id)\b", re.I)
_EMOTION = [
    ("angry", re.compile(r"\b(ridiculous|angry|furious|unacceptable|damn|hell|absurd|sick of|fed up|outrageous)\b", re.I)),
    ("frustrated", re.compile(r"\b(frustrat|already told|again\?|come on|seriously|ugh|waste of time|how many times)\b", re.I)),
    ("anxious", re.compile(r"\b(worried|scared|anxious|stress|nervous|afraid|panic|urgent)\b", re.I)),
    ("confused", re.compile(r"\b(confus|don'?t understand|what do you mean|not sure what|lost)\b", re.I)),
]


class HeuristicPerceiver:
    """Regex perceiver. Good enough to walk the demo offline; the LLM perceiver replaces it live."""

    def perceive(self, text: str, bb: Blackboard) -> Perception:
        t, low = text.strip(), text.lower()
        p = Perception()
        ic = p.identity_candidates
        if m := _RX["policy"].search(t):
            ic.policy_number = f"POL-{m.group(1)}"
        if m := _RX["email"].search(t):
            ic.email = m.group(0)
        if m := _RX["dob"].search(t):
            ic.dob = m.group(1)
        if m := _RX["last4"].search(t):
            ic.id_last4 = m.group(1)
        elif m := _RX["last4_spoken"].search(t):
            ic.id_last4 = m.group(1)
        if m := _RX["phone"].search(t):
            cand = re.sub(r"\D", "", m.group(1))
            if cand not in (re.sub(r"\D", "", ic.dob or ""),) and len(cand) >= 10:
                ic.phone = m.group(1)
        if m := _RX["name"].search(t):
            ic.full_name = m.group(1)
        if m := _RX["rep"].search(t):
            p.caller_role_claim = "representative"
            p.representative = RepresentativeClaim(rep_name=ic.full_name, relationship=(m.group(1) or m.group(2) and "family" or "family").lower())
            if pm := re.search(r"(?:my (?:mother|father|mom|dad|wife|husband)|on behalf of|for)\s+(?:is\s+)?([A-Z][a-z]+\s+[A-Z][a-z]+)", t):
                ic.full_name = pm.group(1)   # the policyholder's name, not the caller's
        elif "policyholder" in low or ic.full_name:
            p.caller_role_claim = "self"

        # intent
        if re.search(r"\b(denied|denial|why was|rejected|turned down)\b", low):
            p.intent = "denial_question"
        elif re.search(r"\b(submit|upload|send (you|in|over)|fax|portal|format|pdf|photo|scan)\b", low):
            p.intent = "document_submission"
        elif re.search(r"\b(next step|what (do|should) i do|what now|what happens|how long|how soon|when)\b", low):
            p.intent = "next_steps"
        elif re.search(r"\b(status|update|where is|progress|open|pending)\b", low):
            p.intent = "status_inquiry"
        elif re.search(r"\b(claim|reimburse|net|fee|amount|allowed|pay|paid)\b", low):
            p.intent = "general_claim_question"

        # case hints
        if re.search(r"\b(health\w*|medical|hospital|doctor|pathology)\b", low):
            p.case_hints.case_type = "healthcare"
        elif re.search(r"\bdental\b", low):
            p.case_hints.case_type = "dental"
        elif re.search(r"\b(auto|car|vehicle|accident)\b", low):
            p.case_hints.case_type = "auto"
        if re.search(r"\b(denied|denial|rejected)\b", low):
            p.case_hints.status = "denied"
        elif re.search(r"\b(open|in progress|pending)\b", low):
            p.case_hints.status = "open"
        elif re.search(r"\b(closed|settled|completed)\b", low):
            p.case_hints.status = "closed"
        if m := re.search(rf"\b({MONTHS})(?:\s+(\d{{4}}))?\b", low):
            if not (ic.dob and m.group(1) in ic.dob.lower()):
                p.case_hints.period = m.group(1) + (f" {m.group(2)}" if m.group(2) else "")
        if m := re.search(r"\b(CL-\d{4})\b", t, re.I):
            p.case_hints.case_id = m.group(1).upper()
        if bb.control.pending == "disambiguate" and bb.control.pending_options:
            idx = {"first": 0, "1": 0, "one": 0, "second": 1, "2": 1, "two": 1, "third": 2, "3": 2}
            for k, i in idx.items():
                if re.search(rf"\b{k}\b", low) and i < len(bb.control.pending_options):
                    p.case_hints.case_id = bb.control.pending_options[i]
                    break
            if not p.case_hints.case_id and (m := re.search(r"\b(20\d{2})\b", low)):
                for opt in bb.control.pending_options:
                    if m.group(1) in opt:
                        p.case_hints.case_id = opt.split(" ")[0]

        # control signals
        p.emotion = next((e for e, rx in _EMOTION if rx.search(low)), "neutral")
        p.refusal = bool(_RX["refusal"].search(low))
        p.wants_human = bool(_RX["human"].search(low))
        p.done = bool(_RX["done"].search(low))
        p.injection_suspected = bool(_RX["injection"].search(low))
        if _RX["yes"].search(t):
            p.consent_signal = "yes"
        elif _RX["no"].search(t):
            p.consent_signal = "no"
            if bb.control.pending == "anything_else":
                p.done = True
        if m := _RX["cant_get"].search(low):
            p.document_unavailable = m.group(2)
        p.new_case_request = bb.phase == "PROCESS_CASE" and bool(_RX["new_case"].search(low)) and (
            p.case_hints.case_type is not None or p.case_hints.case_id is not None)
        if p.injection_suspected or (("?" in t or len(t.split()) > 3) and not _IN_SCOPE.search(low) and not ic.present()):
            p.scope = "out_of_scope"
        if p.intent and not p.identity_candidates.present():
            p.question = t[:200]
        return p
