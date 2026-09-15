"""Output validators.

Leakage is a hard block (regenerate once, then a canned fallback). Grounding is a soft check
(trace warning, ship). Asymmetric on purpose: a leakage false positive costs a slightly stiffer
sentence; a grounding false positive would break the demo. The forbidden set itself comes from
the vertical; the matching and the block/regenerate/fallback loop are generic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from . import prompts
from .cases import MONTHS
from .directive import Directive
from .respond import Responder
from .tools import ToolCtx

AMOUNT_FIELDS = ("expected_reimbursement_amount", "allowed_max_amount", "net_pay", "net_fee")
SHINGLE = 4
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "did", "not", "include", "was", "is",
         "due", "because", "with", "claim", "report", "by", "at", "from", "that", "this", "were", "been"}


@dataclass
class Verdict:
    name: str
    ok: bool
    hard: bool = False
    reason: str = ""


Validator = Callable[[ToolCtx, Directive, str], Verdict]


def _norm(s: str) -> str:
    s = s.lower().replace(",", "")
    return re.sub(r"\s+", " ", s)


def amount_forms(v: str | float) -> set[str]:
    f = float(v)
    return {str(v), f"{f:.2f}", f"{int(f)}" if f.is_integer() else f"{f:.2f}", f"${int(f)}", f"${f:.2f}"}


def date_forms(iso: str) -> set[str]:
    y, m, d = (int(x) for x in iso.split("-"))
    mon = MONTHS[m - 1]
    return {iso, f"{mon} {d} {y}", f"{mon} {d}", f"{d} {mon} {y}", f"{m}/{d}/{y}", f"{mon[:3]} {d} {y}", f"{mon} {d}th {y}"}


def shingles(text: str | None, n: int = SHINGLE) -> set[str]:
    """Word n-grams specific enough to identify the source text (not all stopwords)."""
    if not text:
        return set()
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1)) if not set(w[i:i + n]) <= _STOP}


def forbidden_terms(ctx: ToolCtx) -> dict[str, set[str]]:
    """The vertical's forbidden set minus anything the caller themselves said (echo is not disclosure)."""
    out = ctx.vertical.forbidden_terms(ctx)
    said = _norm(" ".join(m.text for m in ctx.bb.history if m.role == "caller"))
    return {cat: {t for t in terms if t and _norm(t) not in said} for cat, terms in out.items()}


def leakage_guard(ctx: ToolCtx, d: Directive, reply: str) -> Verdict:
    text = _norm(reply)
    for cat, terms in forbidden_terms(ctx).items():
        for t in terms:
            nt = _norm(t)
            if len(nt) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(nt)}(?![a-z0-9])", text):
                ctx.bb.log("safety", event="leak_blocked", category=cat, phase=ctx.bb.phase, term=nt[:2] + "***")
                return Verdict("leakage", ok=False, hard=True, reason=f"{cat} data not disclosable in {ctx.bb.phase}")
    return Verdict("leakage", ok=True)


_NUM = re.compile(r"(?<![a-z])\$?\d[\d,]*(?:\.\d+)?(?![a-z])")


def grounding_guard(ctx: ToolCtx, d: Directive, reply: str) -> Verdict:
    if not ctx.policy.phase(ctx.bb.phase).must_ground or not d.facts:
        return Verdict("grounding", ok=True)
    facts = _norm(json.dumps(d.facts, default=str))
    allowed: set[str] = set()
    for iso in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", facts):
        allowed |= {_norm(x) for x in date_forms(iso)}
    for amt in re.findall(r"\b\d+\.\d{2}\b", facts):
        allowed |= {_norm(x) for x in amount_forms(amt)}
    unknown = []
    for n in _NUM.findall(_norm(reply)):
        bare = n.lstrip("$")
        if bare in facts or n in allowed or bare in allowed or len(bare) <= 1 or any(bare in a for a in allowed):
            continue
        unknown.append(n)
    if unknown:
        ctx.bb.log("validator", name="grounding", ok=False, unknown_numbers=unknown[:5])
        return Verdict("grounding", ok=False, hard=False, reason=f"numbers not in facts: {unknown[:3]}")
    return Verdict("grounding", ok=True)


def default_validators() -> list[Validator]:
    return [leakage_guard, grounding_guard]


def run_validators(ctx: ToolCtx, d: Directive, reply: str, responder: Responder, validators: list[Validator]) -> str:
    bb = ctx.bb
    for attempt in (0, 1):
        blocked: Verdict | None = None
        for v in validators:
            verdict = v(ctx, d, reply)
            if verdict.ok:
                continue
            bb.log("validator", name=verdict.name, ok=False, hard=verdict.hard, reason=verdict.reason, attempt=attempt)
            if verdict.hard:
                blocked = verdict
                break
        if blocked is None:
            return reply
        if attempt == 0:
            d.must_not = [*d.must_not, f"REGENERATION: your previous draft was blocked because it contained {blocked.reason}. "
                                       f"Leave that out entirely."]
            reply = responder.respond(bb, d)
    bb.log("safety", event="canned_fallback", phase=bb.phase)
    return prompts.safe_fallback(ctx.vertical, bb.phase)
