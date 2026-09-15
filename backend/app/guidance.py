"""PROCESS_CASE bundle: the claim record plus every piece of guidance the responder may draw on.

Selection mirrors the guidance file's own structure (intent_hints, requires_documents, match_any)
and applies the precedence rule: claim record > document-specific guidance > topic template >
case_type guidance > default guidance. The deadline on the record overrides "within a week".
"""
from __future__ import annotations

import re

from .data import Store
from .data.models import Claim
from .tools import ToolCtx, dispatch

MAX_TEMPLATES = 2


def _phrase_hits(entry: dict, utterance: str) -> int:
    """Length of the longest match_any phrase found in the utterance (0 = none)."""
    low = utterance.lower()
    return max((len(p) for p in dict.fromkeys(entry.get("match_any", [])) if p in low), default=0)


def select_guidance(store: Store, claim: Claim, intent: str | None, utterance: str) -> list[dict]:
    """Return up to MAX_TEMPLATES followup entries (raw, un-rendered), or the fallback."""
    entries = [g for g in store.guideline["claim_followup_guidance"]
               if (intent is None or intent in g["intent_hints"])
               and (not g.get("requires_documents") or claim.documents_needed)]
    scored = sorted(((_phrase_hits(g, utterance), g) for g in entries), key=lambda x: -x[0])
    phrase_hits = [g for n, g in scored if n > 0]
    if phrase_hits:
        return phrase_hits[:MAX_TEMPLATES]
    intent_only = [g for g in entries if "match_any" not in g and intent is not None]
    if intent_only:
        return intent_only[:MAX_TEMPLATES]
    return [{"topic": "fallback", "en": store.guideline["claim_followup_fallback"]["en"]}]


def _join(docs: list[str]) -> str:
    docs = [f"the {d}" for d in docs]
    if not docs:
        return ""
    return docs[0] if len(docs) == 1 else ", ".join(docs[:-1]) + " and " + docs[-1]


def render(store: Store, entry: dict, claim: Claim) -> str:
    avg = store.guideline["claim_followup_settings"]["average_processing_time_after_submission"]["en"]
    return entry["en"].format(case_id=claim.case_id, documents=_join(claim.documents_needed) or "the requested files",
                              average_processing_time_after_submission=avg)


def deadline_guidance(claim_facts: dict) -> str | None:
    state = claim_facts.get("deadline_state")
    if state is None:
        return None
    dl = claim_facts["appeal_deadline"]
    if state == "passed":
        return (f"The appeal deadline on record was {dl}, which has already passed as of {claim_facts['today']}. "
                f"Do not say 'within a week' and do not promise an appeal or an extension; a human claims "
                f"representative can review what options remain.")
    days = claim_facts["days_until_deadline"]
    return (f"The appeal deadline on record is {dl} ({days} days from today, {claim_facts['today']}). "
            f"Any submission timing must respect that date" + (" — it is sooner than 'within a week'." if days < 7 else "."))


_ALL_WORDS = {"all", "any", "anything", "both", "either", "none", "nothing", "everything", "documents", "records", "paperwork"}


def _resolve_doc(name: str, docs: list[str]) -> list[str]:
    """Map the caller's phrase to documents_needed entries. Blanket phrases ("anything from the
    clinic", "none of those") mean every outstanding document."""
    toks = set(re.findall(r"[a-z]+", name.lower()))
    hits = [d for d in docs if toks & set(d.lower().split())]
    if hits:
        return hits
    return list(docs) if toks & _ALL_WORDS else []


def build_bundle(ctx: ToolCtx) -> dict:
    bb, store = ctx.bb, ctx.store
    case_id = bb.intent.resolved_case
    claim = store.claims_by_id[case_id]
    facts = dispatch(ctx, "get_claim", {"case_id": case_id})
    bundle: dict = {"claim": facts, "documents": [], "followup_guidance": [], "deadline_guidance": deadline_guidance(facts)}
    if claim.case_type in store.guideline["case_type_guidance"]:
        bundle["case_type_guidance"] = store.guideline["case_type_guidance"][claim.case_type]["en"]

    # per-document requirements, always; alternatives only when the caller says they can't obtain something
    unavailable: list[str] = []
    if bb.control.pending == "document_unavailable" and bb.control.pending_options:
        unavailable = _resolve_doc(bb.control.pending_options[0], claim.documents_needed)
    for doc in claim.documents_needed:
        entry = {"name": doc, "state": bb.documents.get(doc, "requested"),
                 "requirements": dispatch(ctx, "get_document_guidance", {"case_id": case_id, "document": doc})["guidance"]}
        if doc in unavailable:
            if bb.documents.get(doc) == "alternative_offered":
                bb.documents[doc] = "declined"
                entry["state"] = "declined"
            else:
                alt = dispatch(ctx, "get_document_alternative", {"case_id": case_id, "document": doc})
                entry["alternative"] = alt["alternative"]
                entry["state"] = "alternative_offered"
        bundle["documents"].append(entry)
    if claim.documents_needed and all(bb.documents.get(d) == "declined" for d in claim.documents_needed):
        bb.control.escalation_reason = "alternatives_exhausted"
        bundle["human_review"] = store.guideline["claim_followup_settings"]["human_review_after_document_alternatives_exhausted"]["en"]
        bb.log("safety", event="alternatives_exhausted", case_id=case_id)

    for entry in select_guidance(store, claim, bb.intent.intent, bb.control.last_utterance):
        if entry["topic"] == "submission_timing" and facts.get("deadline_state") == "passed":
            continue   # the record's deadline beats the "within a week" template
        bundle["followup_guidance"].append({"topic": entry["topic"], "text": render(store, entry, claim)})
    bundle["money_note"] = ("net_pay is what the insurer actually paid; allowed_max_amount is the most it would pay for "
                            "a covered service, not an amount owed to the caller; net_fee is the fee-schedule rate.")
    bb.log("info", event="bundle_built", case_id=case_id, topics=[g["topic"] for g in bundle["followup_guidance"]],
           documents=[(d["name"], d["state"]) for d in bundle["documents"]])
    return bundle
