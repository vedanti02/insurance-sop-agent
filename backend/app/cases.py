"""Case matching: score the verified party's claims against remembered hints.

Joint scoring on case_type, status and created_at month/year. A unique winner resolves;
a near tie stays in RESOLVE_INTENT for disambiguation.
"""
from __future__ import annotations

import re

from .blackboard import CaseHints
from .data.models import Claim

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
RESOLVE_MARGIN = 2


def parse_period(period: str | None) -> tuple[int | None, int | None]:
    if not period:
        return None, None
    low = period.lower()
    month = next((i + 1 for i, m in enumerate(MONTHS) if m[:3] in low), None)
    m = re.search(r"\b(20\d{2})\b", low)
    year = int(m.group(1)) if m else None
    if m2 := re.fullmatch(r"\s*(20\d{2})-(\d{1,2})\s*", low):
        year, month = int(m2.group(1)), int(m2.group(2))
    return month, year


def label(c: Claim) -> str:
    return f"{c.case_type} claim from {MONTHS[c.created_at.month - 1].title()} {c.created_at.year} ({c.status})"


def score(c: Claim, h: CaseHints) -> int:
    s = 0
    if h.case_id and h.case_id.upper() == c.case_id:
        s += 10
    if h.case_type and h.case_type.lower() == c.case_type:
        s += 3
    if h.status and h.status.lower() == c.status:
        s += 2
    month, year = parse_period(h.period)
    if month and month == c.created_at.month:
        s += 2
    if year:
        s += 1 if year == c.created_at.year else -1
    return s


def resolve(claims: list[Claim], hints: CaseHints) -> dict:
    scored = sorted(({"case_id": c.case_id, "score": score(c, hints), "label": label(c),
                      "case_type": c.case_type, "status": c.status, "created_at": c.created_at.isoformat()}
                     for c in claims), key=lambda x: -x["score"])
    if not scored or hints.is_empty():
        return {"candidates": scored, "resolved": None, "ambiguous": False}
    top = scored[0]
    second = scored[1]["score"] if len(scored) > 1 else -99
    if top["score"] > 0 and top["score"] - second >= RESOLVE_MARGIN:
        return {"candidates": scored[:3], "resolved": top["case_id"], "ambiguous": False}
    if top["score"] <= 0:
        return {"candidates": scored, "resolved": None, "ambiguous": False}
    ties = [c for c in scored if c["score"] >= top["score"] - (RESOLVE_MARGIN - 1)]
    return {"candidates": ties, "resolved": None, "ambiguous": True}
