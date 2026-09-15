"""Card dispute vertical tools. Same registry, same enforcement; different records."""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..blackboard import CaseHints
from ..cases import MONTHS, RESOLVE_MARGIN, parse_period
from .insurance import HintArgs, NoArgs
from .registry import ToolCtx, tool

LEDGER: list[dict] = []   # mock provisional-credit ledger


class CaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^DS-\d{4}$")


class EvidenceArgs(CaseArgs):
    document: str = Field(max_length=80)


def label(d) -> str:
    return f"{d.merchant} dispute for ${d.amount} from {MONTHS[d.transaction_date.month - 1].title()} {d.transaction_date.year} ({d.status.replace('_', ' ')})"


def _amount(v: str | None) -> float | None:
    if not v:
        return None
    m = re.search(r"\d+(?:\.\d+)?", v.replace(",", ""))
    return float(m.group(0)) if m else None


def score(d, h: CaseHints) -> int:
    s = 0
    if h.case_id and h.case_id.upper() == d.case_id:
        s += 10
    if h.merchant:
        toks = {t for t in re.findall(r"[a-z]+", h.merchant.lower()) if len(t) >= 3}
        if toks & set(d.merchant.lower().split()):
            s += 3
    a = _amount(h.amount)
    if a is not None and abs(a - float(d.amount)) <= max(1.0, 0.01 * float(d.amount)):
        s += 3
    if h.status and h.status.lower().replace(" ", "_") == d.status:
        s += 2
    month, year = parse_period(h.period)
    if month and month == d.transaction_date.month:
        s += 2
    if year:
        s += 1 if year == d.transaction_date.year else -1
    return s


def _window(d, today: date) -> dict:
    if d.dispute_window_ends is None:
        return {"window_state": None}
    days = (d.dispute_window_ends - today).days
    return {"window_state": "closed" if days < 0 else "open", "days_until_window_ends": days}


@tool("list_my_disputes", tier="autonomous", args=NoArgs, requires_verified=True, description="List the verified cardholder's disputes.")
def list_my_disputes(ctx: ToolCtx, a: NoArgs) -> dict:
    recs = ctx.store.records_by_party.get(ctx.bb.identity.resolved_party or "", [])
    return {"records": [{"case_id": d.case_id, "merchant": d.merchant, "transaction_date": d.transaction_date.isoformat(),
                         "status": d.status, "label": label(d)} for d in recs]}


@tool("find_dispute", tier="autonomous", args=HintArgs, requires_verified=True, description="Score the cardholder's disputes against hints.")
def find_dispute(ctx: ToolCtx, a: HintArgs) -> dict:
    recs = ctx.store.records_by_party.get(ctx.bb.identity.resolved_party or "", [])
    hints = CaseHints(**a.model_dump())
    scored = sorted(({"case_id": d.case_id, "score": score(d, hints), "label": label(d), "merchant": d.merchant,
                      "status": d.status, "transaction_date": d.transaction_date.isoformat()} for d in recs),
                    key=lambda x: -x["score"])
    if not scored or hints.is_empty():
        return {"candidates": scored, "resolved": None, "ambiguous": False}
    top, second = scored[0], (scored[1]["score"] if len(scored) > 1 else -99)
    if top["score"] > 0 and top["score"] - second >= RESOLVE_MARGIN:
        return {"candidates": scored[:3], "resolved": top["case_id"], "ambiguous": False}
    if top["score"] <= 0:
        return {"candidates": scored, "resolved": None, "ambiguous": False}
    return {"candidates": [c for c in scored if c["score"] >= top["score"] - (RESOLVE_MARGIN - 1)], "resolved": None, "ambiguous": True}


@tool("get_dispute", tier="autonomous", args=CaseArgs, requires_verified=True, description="Full record for one of the cardholder's disputes.")
def get_dispute(ctx: ToolCtx, a: CaseArgs) -> dict:
    d = ctx.store.records_by_id[a.case_id]
    out = d.model_dump(mode="json", exclude={"party_id"})
    out.update(_window(d, ctx.settings.demo_today))
    out["label"] = label(d)
    out["today"] = ctx.settings.demo_today.isoformat()
    return out


@tool("get_evidence_guidance", tier="autonomous", args=EvidenceArgs, requires_verified=True, description="What a piece of evidence must show.")
def get_evidence_guidance(ctx: ToolCtx, a: EvidenceArgs) -> dict:
    g = ctx.store.guideline["evidence_guidance"].get(a.document.lower())
    return {"document": a.document, "guidance": g or ctx.store.guideline["default_guidance"], "specific": g is not None}


@tool("draft_dispute_summary", tier="autonomous", args=NoArgs, requires_verified=True, description="Recap plus the provisional-credit offer, if one applies.")
def draft_dispute_summary(ctx: ToolCtx, a: NoArgs) -> dict:
    bb, store = ctx.bb, ctx.store
    ids = [c for c in [*bb.intent.handled_cases, bb.intent.resolved_case] if c]
    seen: list[str] = []
    ids = [c for c in ids if not (c in seen or seen.append(c))]
    disputes, offer = [], None
    for cid in ids:
        d = store.records_by_id[cid]
        entry = {"case_id": cid, "merchant": d.merchant, "amount": d.amount, "status": d.status}
        if d.evidence_needed:
            entry["evidence_needed"] = d.evidence_needed
        if d.dispute_window_ends:
            entry["dispute_window_ends"] = d.dispute_window_ends.isoformat()
        if d.provisional_credit_status == "offered" and offer is None:
            offer = {"case_id": cid, "amount": d.provisional_credit_amount, "terms": store.guideline["provisional_credit_terms"]}
        disputes.append(entry)
    return {"disputes": disputes, "provisional_credit_offer": offer, "offer_available": offer is not None,
            "no_disputes_on_file": bb.intent.no_claims, "as_of": ctx.settings.demo_today.isoformat()}


@tool("acknowledge_provisional_credit", tier="ask_first", args=NoArgs, requires_verified=True,
      description="Apply the offered provisional credit after the cardholder explicitly accepts its terms.")
def acknowledge_provisional_credit(ctx: ToolCtx, a: NoArgs) -> dict:
    offer = (ctx.bb.post_process.summary or {}).get("provisional_credit_offer")
    if not offer:
        return {"applied": False, "reason": "no offer on this session"}
    d = ctx.store.records_by_id[offer["case_id"]]
    if d.party_id != ctx.bb.identity.resolved_party:
        return {"applied": False, "reason": "not the cardholder's dispute"}
    d.provisional_credit_status = "applied"
    ref = f"PC-{d.case_id[3:]}"
    LEDGER.append({"session_id": ctx.bb.session_id, "case_id": d.case_id, "amount": offer["amount"], "reference": ref})
    ctx.bb.post_process.receipt = ref
    return {"applied": True, "amount": offer["amount"], "reference": ref}
