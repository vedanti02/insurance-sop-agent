"""Email summary drafted from the blackboard, never from the transcript."""
from __future__ import annotations

from .tools.registry import ToolCtx

_INTENT_TOPIC = {
    "denial_question": "why the claim was denied",
    "document_submission": "how to submit the requested documents",
    "next_steps": "next steps on the claim",
    "status_inquiry": "the current claim status",
    "general_claim_question": "general questions about the claim",
}


def build_summary(ctx: ToolCtx) -> dict:
    bb, store, today = ctx.bb, ctx.store, ctx.settings.demo_today
    case_ids = [c for c in [*bb.intent.handled_cases, bb.intent.resolved_case] if c]
    seen: list[str] = []
    case_ids = [c for c in case_ids if not (c in seen or seen.append(c))]
    topics = sorted({_INTENT_TOPIC[t.data["intent"]] for t in bb.trace
                     if t.kind == "memory" and t.data.get("event") == "intent_captured" and t.data.get("intent") in _INTENT_TOPIC})
    cases_out, follow_ups = [], []
    for cid in case_ids:
        c = store.claims_by_id[cid]
        entry = {"case_id": cid, "case_type": c.case_type, "status": c.status, "outcome": c.summary}
        if c.documents_needed:
            entry["documents_needed"] = c.documents_needed
            follow_ups.append(f"Submit for {cid}: {', '.join(c.documents_needed)} (member portal or claim upload link).")
        if c.appeal_deadline:
            state = "passed" if c.appeal_deadline < today else "upcoming"
            entry["appeal_deadline"] = c.appeal_deadline.isoformat()
            entry["deadline_state"] = state
            follow_ups.append(f"Appeal deadline for {cid}: {c.appeal_deadline.isoformat()}"
                              + (" — this date has passed; a representative can review options." if state == "passed" else "."))
        for doc, state in bb.documents.items():
            if state == "alternative_offered":
                follow_ups.append(f"If the {doc} cannot be obtained, request a replacement copy from the provider first.")
        cases_out.append(entry)
    if bb.control.escalation_reason:
        follow_ups.append("A human claims representative will follow up.")
    return {"topics_discussed": topics or ["your account"], "cases": cases_out,
            "no_claims_on_file": bb.intent.no_claims, "follow_ups": follow_ups, "as_of": today.isoformat()}
