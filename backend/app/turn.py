"""The turn loop: perceive -> absorb -> [act -> gate]* -> directive -> respond -> validate -> commit."""
from __future__ import annotations

from dataclasses import dataclass, field

from .blackboard import Message, mask_pii
from .directive import Directive, build_directive
from .machine import TERMINAL, next_exit, transition
from .memory import absorb
from .perceive import Perceiver
from .respond import Responder
from .tools import ToolCtx, ToolError, dispatch
from .validate import Validator, run_validators
from .verify import update_access, verify_candidates

MAX_HOPS = 6


@dataclass
class TurnResult:
    reply: str
    phase: str
    transitions: list[dict]
    trace: list[dict] = field(default_factory=list)


def _on_enter(ctx: ToolCtx, phase: str, frm: str) -> None:
    bb = ctx.bb
    if phase == "RESOLVE_INTENT":
        if frm == "PROCESS_CASE" and bb.intent.resolved_case:
            bb.intent.handled_cases.append(bb.intent.resolved_case)
        bb.intent.resolved_case, bb.intent.candidate_cases = None, []
        bb.intent.new_case_request, bb.intent.handled = False, False
        bb.control.done = False
    elif phase == "PROCESS_CASE" and frm == "POST_PROCESS":
        bb.post_process.summary = None
    elif phase == "POST_PROCESS":
        bb.control.done = True


def act(ctx: ToolCtx) -> None:
    """Deterministic, phase-specific harness work. No model calls."""
    bb, store, pol = ctx.bb, ctx.store, ctx.policy
    it, c = bb.intent, bb.control
    if bb.phase == "VERIFY_ID":
        ident, con = bb.identity, bb.post_process.consent
        if ident.candidates:
            res = verify_candidates(bb, store, pol)
            bb.log("tool", name="verify_identity", tier="autonomous", args={"fields": list(ident.candidates)}, result=res)
            ident.candidates = {}
        if ident.caller_role == "representative" and ident.resolved_party and hasattr(store, "reps_by_buyer"):
            if not ident.rep_verified and ident.rep_name:
                dispatch(ctx, "identify_representative", {"rep_name": ident.rep_name, "relationship": ident.rep_relationship})
            if ident.rep_verified and bb.verified_count >= pol.verification.required_fields:
                if con.state == "none":
                    # the representative's request for access is the in-channel ask; the policyholder must approve
                    dispatch(ctx, "request_consent", confirmed=True)
                elif con.state == "pending":
                    seq = len(store.consent_scenarios[con.scenario].status_sequence)
                    while con.state == "pending" and con.polls < seq:
                        dispatch(ctx, "check_consent_status")
                    if con.state == "denied":
                        c.escalation_reason = "consent_not_granted"
                        bb.log("safety", event="consent_not_granted", polls=con.polls)
        update_access(bb, pol)
    elif bb.phase == "RESOLVE_INTENT":
        B = ctx.vertical.BINDINGS
        if not store.records_by_party.get(bb.identity.resolved_party or ""):
            it.no_claims = True
            return
        if it.case_hints.is_empty():
            it.candidate_cases = dispatch(ctx, B["list"])["records"]
            return
        res = dispatch(ctx, B["resolve"], it.case_hints.model_dump(exclude_none=True))
        it.candidate_cases = res["candidates"]
        if res["resolved"]:
            it.resolved_case, it.resolved_turn = res["resolved"], bb.turn
            it.case_hints.case_id = res["resolved"]
    elif bb.phase == "PROCESS_CASE" and it.resolved_case:
        bb.bundle = ctx.vertical.build_bundle(ctx)
        it.handled = True
    elif bb.phase == "POST_PROCESS":
        B, pp = ctx.vertical.BINDINGS, bb.post_process
        if pp.summary is None:
            pp.summary = dispatch(ctx, B["summary"])
            if not pp.summary.get("offer_available", True):
                pp.decision = "not_offered"   # nothing to offer this caller; close after the recap
        if pp.decision == "accept" and pp.receipt is None:
            dispatch(ctx, B["finish"], confirmed=True)


def run_turn(ctx: ToolCtx, text: str, perceiver: Perceiver, responder: Responder,
             validators: list[Validator] | None = None) -> TurnResult:
    bb = ctx.bb
    bb.turn += 1
    bb.model_calls_this_turn = 0
    bb.history.append(Message(role="caller", text=text, turn=bb.turn))
    start = len(bb.trace)
    transitions: list[dict] = []

    if not bb.closed:
        perception = perceiver.perceive(text, bb)
        bb.log("perception", **perception.model_dump(exclude_none=True, exclude_defaults=True))
        absorb(bb, perception, text, ctx.policy)
        for _ in range(MAX_HOPS):
            try:
                act(ctx)
            except ToolError as e:
                bb.log("info", event="tool_error", detail=str(e))
            ex = next_exit(bb, ctx.policy)
            if ex is None:
                break
            frm = bb.phase
            transition(bb, ex)
            transitions.append({"from": frm, "to": ex.to, "predicate": ex.when})
            _on_enter(ctx, ex.to, frm)
            if bb.phase in TERMINAL:
                try:
                    act(ctx)
                except ToolError:
                    pass
                break

    directive = build_directive(ctx)
    bb.log("directive", goal=directive.goal, ask=directive.ask, style=directive.style,
           must_not=directive.must_not, tone=directive.tone, fact_keys=list(directive.facts))
    reply = responder.respond(bb, directive)
    reply = run_validators(ctx, directive, reply, responder, validators or [])
    bb.history.append(Message(role="agent", text=reply, turn=bb.turn))
    return TurnResult(reply=reply, phase=bb.phase, transitions=transitions,
                      trace=[mask_pii(t.model_dump(mode="json")) for t in bb.trace[start:]])
