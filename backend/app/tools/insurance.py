"""Insurance vertical tools. Read tools are autonomous; anything that sends or authorizes is ask_first."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .. import cases
from ..blackboard import CaseHints
from ..normalize import matches
from ..verify import identify_representative
from .registry import ToolCtx, tool

OUTBOX: list[dict] = []   # mock email service


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    value: str = Field(max_length=80)


class RepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rep_name: str | None = None
    relationship: str | None = None


class CaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^CL-\d{4}$")


class DocArgs(CaseArgs):
    document: str = Field(max_length=80)


class FollowupArgs(CaseArgs):
    intent: str | None = None
    utterance: str = Field(default="", max_length=500)


class FieldNameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=40)


class ReasonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(max_length=120)


# --- VERIFY_ID -----------------------------------------------------------------------
@tool("verify_identity", tier="autonomous", args=FieldArgs, description="Check one identity field. Returns booleans only.")
def verify_identity(ctx: ToolCtx, a: FieldArgs) -> dict:
    ident = ctx.bb.identity
    if ident.resolved_party is None or a.field not in ctx.policy.verification.fields:
        return {"field": a.field, "match": False, "verified_count": len(ident.verified_fields)}
    ok = matches(a.field, a.value, ctx.store.by_party[ident.resolved_party])
    if ok and a.field not in ident.verified_fields:
        ident.verified_fields.append(a.field)
    return {"field": a.field, "match": ok, "verified_count": len(ident.verified_fields),
            "remaining_required": max(0, ctx.policy.verification.required_fields - len(ident.verified_fields))}


@tool("identify_representative", tier="autonomous", args=RepArgs, description="Check a representative claim against the record.")
def identify_representative_tool(ctx: ToolCtx, a: RepArgs) -> dict:
    party = ctx.bb.identity.resolved_party
    ok = bool(party) and identify_representative(ctx.store, a.rep_name, a.relationship, party)
    ctx.bb.identity.rep_verified = ok
    return {"matched": ok}


@tool("request_consent", tier="ask_first", args=NoArgs, description="Ask the policyholder to authorize the representative.")
def request_consent(ctx: ToolCtx, a: NoArgs) -> dict:
    con = ctx.bb.post_process.consent
    con.state, con.polls = "pending", 0
    return {"state": con.state}


@tool("check_consent_status", tier="autonomous", args=NoArgs, description="Poll the consent service once.")
def check_consent_status(ctx: ToolCtx, a: NoArgs) -> dict:
    con = ctx.bb.post_process.consent
    seq = ctx.store.consent_scenarios[con.scenario].status_sequence
    if con.state == "pending":
        status = seq[con.polls] if con.polls < len(seq) else "denied"
        con.polls += 1
        if status == "approved":
            con.state = "approved"
        elif con.polls >= len(seq):
            con.state = "denied"   # exhausted the sequence without approval
    return {"state": con.state, "polls": con.polls}


# --- RESOLVE_INTENT ------------------------------------------------------------------
@tool("list_my_claims", tier="autonomous", args=NoArgs, requires_verified=True, description="List the verified party's claims (ids, type, status, date).")
def list_my_claims(ctx: ToolCtx, a: NoArgs) -> dict:
    claims = ctx.store.claims_by_party.get(ctx.bb.identity.resolved_party or "", [])
    return {"records": [{"case_id": c.case_id, "case_type": c.case_type, "status": c.status,
                         "created_at": c.created_at.isoformat(), "label": cases.label(c)} for c in claims]}


class HintArgs(BaseModel):
    """The CaseHints shape; every vertical's resolve tool takes it."""
    model_config = ConfigDict(extra="forbid")
    case_type: str | None = None
    status: str | None = None
    period: str | None = None
    case_id: str | None = None
    merchant: str | None = None
    amount: str | None = None


@tool("find_case", tier="autonomous", args=HintArgs, requires_verified=True, description="Score the party's claims against hints.")
def find_case(ctx: ToolCtx, a: HintArgs) -> dict:
    claims = ctx.store.claims_by_party.get(ctx.bb.identity.resolved_party or "", [])
    return cases.resolve(claims, CaseHints(**a.model_dump()))


# --- PROCESS_CASE --------------------------------------------------------------------
def _deadline_state(deadline: date | None, today: date) -> dict:
    if deadline is None:
        return {"appeal_deadline": None, "deadline_state": None}
    days = (deadline - today).days
    return {"appeal_deadline": deadline.isoformat(), "deadline_state": "passed" if days < 0 else "upcoming",
            "days_until_deadline": days}


@tool("get_claim", tier="autonomous", args=CaseArgs, requires_verified=True, description="Full record for one of the party's claims.")
def get_claim(ctx: ToolCtx, a: CaseArgs) -> dict:
    c = ctx.store.claims_by_id[a.case_id]
    out = c.model_dump(mode="json", exclude={"party_id"})
    out.update(_deadline_state(c.appeal_deadline, ctx.settings.demo_today))
    out["label"] = cases.label(c)
    out["field_meanings"] = {k: v["description"] for k, v in ctx.store.claim_schema["field_descriptions"].items()}
    out["today"] = ctx.settings.demo_today.isoformat()
    return out


@tool("get_document_guidance", tier="autonomous", args=DocArgs, requires_verified=True, description="Requirements for one requested document.")
def get_document_guidance(ctx: ToolCtx, a: DocArgs) -> dict:
    key = ctx.store.resolve_document_key(a.document)
    return {"document": a.document, "resolved_key": key, "guidance": ctx.store.document_guidance(a.document),
            "specific": key is not None}


@tool("get_document_alternative", tier="autonomous", args=DocArgs, requires_verified=True, description="What to do if a document cannot be obtained.")
def get_document_alternative(ctx: ToolCtx, a: DocArgs) -> dict:
    key = ctx.store.resolve_document_key(a.document)
    ctx.bb.documents[a.document] = "alternative_offered"
    return {"document": a.document, "resolved_key": key, "alternative": ctx.store.document_alternative(a.document)}


@tool("explain_field", tier="autonomous", args=FieldNameArgs, requires_verified=True, description="Meaning of a claim money field.")
def explain_field(ctx: ToolCtx, a: FieldNameArgs) -> dict:
    desc = ctx.store.claim_schema["field_descriptions"].get(a.field)
    return {"field": a.field, "description": desc["description"] if desc else None}


# --- POST_PROCESS --------------------------------------------------------------------
@tool("draft_summary", tier="autonomous", args=NoArgs, requires_verified=True, description="Build the email summary from the blackboard.")
def draft_summary(ctx: ToolCtx, a: NoArgs) -> dict:
    from ..summary import build_summary
    return {**build_summary(ctx), "offer_available": True}


@tool("send_summary_email", tier="ask_first", args=NoArgs, requires_verified=True, description="Send the drafted summary to the address on file.")
def send_summary_email(ctx: ToolCtx, a: NoArgs) -> dict:
    party = ctx.store.by_party[ctx.bb.identity.resolved_party]   # recipient resolved server-side, always
    local, _, domain = party.email.partition("@")
    masked = f"{local[0]}***@{domain}"
    OUTBOX.append({"session_id": ctx.bb.session_id, "to": party.email, "to_masked": masked,
                   "summary": ctx.bb.post_process.summary})
    ctx.bb.post_process.receipt = masked
    return {"sent": True, "to_masked": masked}


@tool("transfer_to_human", tier="autonomous", args=ReasonArgs, description="Hand the session to a human representative.")
def transfer_to_human(ctx: ToolCtx, a: ReasonArgs) -> dict:
    ctx.bb.control.wants_human = True
    ctx.bb.control.escalation_reason = ctx.bb.control.escalation_reason or a.reason
    return {"transferred": True, "reason": a.reason}
