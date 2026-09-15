"""Absorb one perception into the blackboard. This is the cross-phase memory: every signal
is stored with the turn it arrived, regardless of phase; the machine decides when it is used."""
from __future__ import annotations

from .blackboard import Blackboard
from .perceive import Perception
from .policy import Policy


def absorb(bb: Blackboard, p: Perception, text: str, policy: Policy) -> None:
    c, ident, it = bb.control, bb.identity, bb.intent
    c.last_utterance = text

    # identity candidates -> harness verification (never verified_fields directly)
    cands = p.identity_candidates.present()
    if cands and bb.verified_count < policy.verification.required_fields:
        ident.candidates = cands
    if p.caller_role_claim and ident.caller_role is None:
        ident.caller_role = p.caller_role_claim
    if p.representative and (p.representative.rep_name or p.representative.relationship):
        ident.caller_role = "representative"
        ident.rep_name = p.representative.rep_name or ident.rep_name
        ident.rep_relationship = p.representative.relationship or ident.rep_relationship

    # intent + case hints: remembered even in VERIFY_ID, surfaced only after the gate opens
    if p.intent:
        it.intent = p.intent
        if it.intent_turn is None:
            it.intent_turn = bb.turn
        bb.log("memory", event="intent_captured", intent=p.intent, phase=bb.phase,
               deferred=bb.phase == "VERIFY_ID")
    if not p.case_hints.is_empty():
        replace = p.new_case_request and bb.phase == "PROCESS_CASE"
        it.case_hints = p.case_hints if replace else it.case_hints.merged(p.case_hints)
        if it.hints_turn is None or replace:
            it.hints_turn = bb.turn
        bb.log("memory", event="case_hints_captured", hints=p.case_hints.model_dump(exclude_none=True),
               phase=bb.phase, deferred=bb.phase == "VERIFY_ID")
    if p.new_case_request and bb.phase == "PROCESS_CASE":
        it.new_case_request = True

    # scope
    if p.scope == "out_of_scope":
        c.scope_strikes += 1
        if p.injection_suspected:
            c.injection_suspected = True
        bb.log("safety", event="injection_suspected" if p.injection_suspected else "out_of_scope",
               strikes=c.scope_strikes)
    else:
        c.scope_strikes = 0
    c.ungrounded_question = False

    # affect + escalation
    c.emotion = p.emotion
    c.refusal = p.refusal
    if p.wants_human:
        c.wants_human = True
        c.escalation_reason = c.escalation_reason or "caller_requested_human"

    # answers to whatever we asked last turn
    done = p.done
    if c.pending == "post_offer" and p.consent_signal:
        bb.post_process.decision = "accept" if p.consent_signal == "yes" else "decline"
    elif c.pending == "offer_human" and p.consent_signal == "yes":
        c.wants_human = True
        c.escalation_reason = c.escalation_reason or "caller_accepted_transfer"
    elif c.pending == "anything_else" and p.consent_signal == "no":
        done = True
    if done:
        if bb.phase == "POST_PROCESS" and bb.post_process.decision is None and c.pending == "post_offer":
            bb.post_process.decision = "decline"
        c.done = True
    elif bb.phase == "POST_PROCESS" and p.intent is not None and p.consent_signal is None:
        c.done = False  # one more question -> back to PROCESS_CASE
    if p.document_unavailable:
        c.pending = "document_unavailable"
        c.pending_options = [p.document_unavailable]
