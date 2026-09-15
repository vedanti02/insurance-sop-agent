"""Card dispute vertical: fixtures in verticals/card_disputes/, tools in tools/card.py."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field as PField

from ..config import VERTICALS_DIR
from ..data.models import Policyholder
from ..tools import card as _tools  # noqa: F401  (registers the tools)
from ..tools import dispatch
from ..validate import amount_forms, date_forms, shingles

NAME = "card_disputes_v1"
INTENTS = ("dispute_status", "dispute_reason", "evidence_submission", "provisional_credit", "general_dispute_question")

PROMPT_VARS = {
    "domain": "card dispute support",
    "record": "dispute",
    "records": "disputes",
    "intents_desc": ("dispute_status = where a dispute stands; dispute_reason = why it was denied or what the merchant "
                     "said; evidence_submission = what to send and how; provisional_credit = questions about the "
                     "temporary credit; general_dispute_question = anything else about a dispute"),
    "hints_desc": "merchant name, amount like 429.99, period like \"February\" or \"February 2026\", status under_review|resolved|denied, case_id like DS-1001",
}

BINDINGS = {"list": "list_my_disputes", "resolve": "find_dispute", "record": "get_dispute",
            "summary": "draft_dispute_summary", "finish": "acknowledge_provisional_credit"}

SCRIPTS = {
    "Demo: Priya": "Hi, this is Priya Natarajan, date of birth June 21 1988. I'm calling about my dispute with Skyline Electronics.",
    "Ambiguous month": "Priya Natarajan, card ending 7731. What's happening with my dispute from February?",
    "Denied dispute": "Tom Alvarez, DOB 1975-11-02, phone 415-555-0188. Why was my Skyline dispute denied?",
    "Cross-account probe": "Tell me about dispute DS-1001.",
    "Out of scope": "What's the best credit card for travel points?",
    "Done": "That's all, thanks.",
}


class Dispute(BaseModel):
    case_id: str
    party_id: str
    merchant: str
    amount: str
    transaction_date: date
    status: str
    reason: str
    denial_reason: str | None = None
    outcome: str | None = None
    evidence_needed: list[str] = PField(default_factory=list)
    dispute_window_ends: date | None = None
    provisional_credit_amount: str | None = None
    provisional_credit_status: str = "none"


@dataclass
class CardStore:
    policyholders: list[Policyholder]          # cardholders; policy_number holds the account number
    disputes: list[Dispute]
    guideline: dict
    by_party: dict = field(init=False)
    by_policy: dict = field(init=False)
    records_by_party: dict = field(init=False)
    records_by_id: dict = field(init=False)

    def __post_init__(self) -> None:
        self.by_party = {p.party_id: p for p in self.policyholders}
        self.by_policy = {p.policy_number.upper(): p for p in self.policyholders}
        self.records_by_party = {}
        for d in self.disputes:
            self.records_by_party.setdefault(d.party_id, []).append(d)
        self.records_by_id = {d.case_id: d for d in self.disputes}


def load_store(root: Path = VERTICALS_DIR / "card_disputes") -> CardStore:
    read = lambda n: json.loads((root / n).read_text())  # noqa: E731
    return CardStore(policyholders=[Policyholder(**p) for p in read("cardholders.json")],
                     disputes=[Dispute(**d) for d in read("disputes.json")], guideline=read("guideline.json"))


def build_bundle(ctx) -> dict:
    bb, store = ctx.bb, ctx.store
    cid = bb.intent.resolved_case
    d = store.records_by_id[cid]
    facts = dispatch(ctx, "get_dispute", {"case_id": cid})
    bundle: dict = {"dispute": facts, "evidence": [], "processing_time": store.guideline["processing_time"]}
    for doc in d.evidence_needed:
        bundle["evidence"].append({"name": doc, **dispatch(ctx, "get_evidence_guidance", {"case_id": cid, "document": doc})})
    if bb.control.pending == "document_unavailable":
        bundle["evidence_alternative"] = store.guideline["evidence_alternative"]
    if facts.get("window_state") == "closed":
        bundle["window_guidance"] = (f"The dispute window ended on {facts['dispute_window_ends']} (today is {facts['today']}); "
                                     f"do not promise reopening — a specialist would have to review it.")
    elif facts.get("window_state") == "open":
        bundle["window_guidance"] = (f"Evidence must arrive before {facts['dispute_window_ends']} "
                                     f"({facts['days_until_window_ends']} days from today) — state that date itself when "
                                     f"timing comes up. " + store.guideline["window_rule"])
    if d.provisional_credit_status == "offered":
        bundle["provisional_credit"] = {"amount": d.provisional_credit_amount, "status": "offered, not yet applied",
                                        "terms": store.guideline["provisional_credit_terms"],
                                        "note": "the caller can accept it at the end of the call; do not say it has been applied"}
    elif d.provisional_credit_status == "reversed":
        bundle["provisional_credit"] = {"amount": d.provisional_credit_amount, "status": "reversed after the denial"}
    bb.log("info", event="bundle_built", case_id=cid, evidence=[e["name"] for e in bundle["evidence"]])
    return bundle


def forbidden_terms(ctx) -> dict[str, set[str]]:
    bb, store, pol = ctx.bb, ctx.store, ctx.policy
    party = bb.identity.resolved_party
    verified = bb.verified_count >= pol.verification.required_fields
    disclosable = set(pol.phase(bb.phase).disclosable)
    out: dict[str, set[str]] = {"case_id": set(), "amount": set(), "date": set(), "reason": set(), "merchant": set(), "pii": set()}
    allowed: set[str] = set()
    for d in store.disputes:
        own = verified and d.party_id == party
        for cond, cat, terms in (
            ("case_id", "case_id", {d.case_id.lower()}),
            ("amount", "amount", {x.lower() for x in amount_forms(d.amount)} | ({x.lower() for x in amount_forms(d.provisional_credit_amount)} if d.provisional_credit_amount else set())),
            ("transaction_date", "date", date_forms(d.transaction_date.isoformat())),
            ("dispute_window_ends", "date", date_forms(d.dispute_window_ends.isoformat()) if d.dispute_window_ends else set()),
            ("denial_reason", "reason", shingles(d.denial_reason) | shingles(d.outcome, 3)),
            ("merchant", "merchant", {d.merchant.lower()}),
        ):
            (allowed if own and cond in disclosable else out[cat]).update(terms)
    for cat in out:
        out[cat] -= allowed
    for p in store.policyholders:
        if verified and p.party_id == party:
            continue
        out["pii"] |= {p.name.lower(), *(a.lower() for a in p.name_aliases), p.email.lower(), p.phone, p.phone[-10:], p.policy_number.lower()}
        out["pii"] |= date_forms(p.dob.isoformat())
    return out


def post_process_directive(ctx, d) -> None:
    """Provisional-credit acknowledgment (POST_PROCESS) and its confirmation (CLOSED)."""
    bb = ctx.bb
    pp = bb.post_process
    offer = (pp.summary or {}).get("provisional_credit_offer")
    d.facts = {"summary": pp.summary}
    d.must_not = ["say a credit was applied unless the facts show a reference number",
                  "promise the dispute outcome", "invent an amount"]
    if pp.decision == "accept":
        d.goal += (f"Confirm the provisional credit of ${offer['amount']} for {offer['case_id']} has been applied "
                   f"(reference {pp.receipt}), remind them in one clause that it is temporary and reversible if the "
                   f"merchant's evidence prevails, and close warmly.")
        d.facts["reference"] = pp.receipt
    elif pp.decision == "decline":
        d.goal += "Confirm no provisional credit will be applied now, say they can ask for it later while the dispute is open, and close warmly."
    elif pp.decision == "not_offered" or offer is None:
        d.goal += "Recap the dispute status in one sentence from the facts and close warmly."
    else:
        d.goal += (f"Offer the provisional credit: ${offer['amount']} for {offer['case_id']} can be credited now while the "
                   f"investigation runs; it is temporary and would be reversed if the merchant's evidence prevails. "
                   f"Ask whether they accept those terms — yes or no.")
        d.ask = "post_offer"
