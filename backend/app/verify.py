"""Harness-driven identity verification. Runs after perception, before the responder.

Returns booleans only. Never the stored value, on a match or a near miss. Resolution
(which record we are checking against) is separate from verification (how many fields
matched) so a policy number alone always yields verified_count 0.
"""
from __future__ import annotations

import re

from .blackboard import Blackboard
from .data import Policyholder, Store
from .normalize import matches, norm_name
from .policy import Policy

VERIFIABLE = ("full_name", "dob", "phone", "email", "id_last4")
STRONG_FIELDS = ("phone", "email", "id_last4")


def _norm_policy(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    return f"POL-{digits}" if digits else v.upper()


def find_party(store: Store, cands: dict[str, str]) -> Policyholder | None:
    """Resolve a record from a policy number, a uniquely matching name, or two other fields."""
    if pol := cands.get("policy_number"):
        if p := store.by_policy.get(_norm_policy(pol)):
            return p
    others = [f for f in VERIFIABLE if f != "full_name" and cands.get(f)]
    if name := cands.get("full_name"):
        hits = [p for p in store.policyholders if matches("full_name", name, p)]
        if len(hits) > 1 and others:
            hits = [p for p in hits if any(matches(f, cands[f], p) for f in others)]
        if len(hits) == 1:
            return hits[0]
    if len(others) >= 2:
        hits = [p for p in store.policyholders if sum(matches(f, cands[f], p) for f in others) >= 2]
        if len(hits) == 1:
            return hits[0]
    return None


def verify_candidates(bb: Blackboard, store: Store, policy: Policy) -> dict:
    """Evaluate every candidate field supplied this turn against the resolved record."""
    ident, vp = bb.identity, policy.verification
    cands = dict(ident.candidates)
    if ident.locked or not cands:
        return {"evaluated": [], "verified_count": len(ident.verified_fields)}

    given = [f for f in vp.fields if cands.get(f)]
    if ident.resolved_party is None:
        party = find_party(store, cands)
        if party is not None:
            ident.resolved_party = party.party_id
            bb.log("memory", event="party_resolved", via=[k for k in cands if k == "policy_number" or k in given])
        else:
            if cands.get("policy_number"):
                ident.unknown_policy_attempts += 1
            if given or cands.get("policy_number"):
                ident.mismatched_turns += 1
                ident.mismatched_fields_last_turn = given or ["policy_number"]
            _maybe_lock(bb, vp.mismatch_turns_lock)
            return {"evaluated": [{"field": f, "match": False} for f in given], "resolved": False,
                    "verified_count": 0, "remaining_required": vp.required_fields}

    record = store.by_party[ident.resolved_party]
    # A field already verified stays verified; re-extractions of it (e.g. a first name echoed from
    # context) must not count as a new attempt.
    given = [f for f in given if f not in ident.verified_fields]
    evaluated = [{"field": f, "match": matches(f, cands[f], record)} for f in given]
    mismatched = [e["field"] for e in evaluated if not e["match"]]
    # A wrong strong field (the ones a stranger can't guess from a name) fails the whole turn:
    # nothing is credited. A weak-field miss (name/DOB typo, ASR noise) still credits the rest.
    strong_miss = any(f in STRONG_FIELDS for f in mismatched)
    for e in evaluated:
        if e["match"] and not strong_miss and e["field"] not in ident.verified_fields:
            ident.verified_fields.append(e["field"])
    ident.mismatched_fields_last_turn = mismatched
    if mismatched:
        ident.mismatched_turns += 1
    _maybe_lock(bb, vp.mismatch_turns_lock)
    count = len(ident.verified_fields)
    return {"evaluated": evaluated, "resolved": True, "verified_count": count,
            "remaining_required": max(0, vp.required_fields - count)}


def _maybe_lock(bb: Blackboard, lock_at: int) -> None:
    if bb.identity.mismatched_turns >= lock_at and not bb.identity.locked:
        bb.identity.locked = True
        bb.control.escalation_reason = "verification_locked"
        bb.log("safety", event="verification_locked", mismatched_turns=bb.identity.mismatched_turns)


def update_access(bb: Blackboard, policy: Policy) -> bool:
    """The single predicate the VERIFY_ID exit reads: enough fields, and consent if a representative."""
    ident = bb.identity
    ok = len(ident.verified_fields) >= policy.verification.required_fields and not ident.locked
    if ident.caller_role == "representative":
        ok = ok and ident.rep_verified and bb.post_process.consent.state == "approved"
    ident.access_granted = ok
    return ok


def identify_representative(store: Store, rep_name: str | None, relationship: str | None, party_id: str) -> bool:
    """Name on the representatives record is the key. The stated relationship is informational only:
    callers phrase it from either side ("her son" / "my mother") and the policyholder's consent is the
    real authorization."""
    if not rep_name:
        return False
    return any(norm_name(rep.rep_name) == norm_name(rep_name) for rep in store.reps_by_buyer.get(party_id, []))
