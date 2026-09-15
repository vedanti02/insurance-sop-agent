"""Phase graph. One step at a time so the turn loop can run harness work between hops."""
from __future__ import annotations

from .blackboard import Blackboard
from .policy import Exit, Policy, evaluate

TERMINAL = {"CLOSED", "HANDOFF"}


def next_exit(bb: Blackboard, policy: Policy) -> Exit | None:
    if bb.phase in TERMINAL:
        return None
    state = bb.model_dump(mode="json")
    for ex in policy.global_exits + policy.phase(bb.phase).exits:
        if ex.to != bb.phase and evaluate(ex.when, state):
            return ex
    return None


def transition(bb: Blackboard, ex: Exit) -> None:
    bb.log("transition", frm=bb.phase, to=ex.to, predicate=ex.when)
    bb.phase = ex.to
    if ex.to in TERMINAL:
        bb.closed = True
