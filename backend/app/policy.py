"""PhasePolicy loading and the predicate evaluator.

Predicates are `<dotted.path> <op> <literal>` with ops ==, !=, >=, <=, in, count>=.
No eval. The literal is null/true/false/int/string/[a, b].
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .config import VERTICALS_DIR


class Exit(BaseModel):
    when: str
    to: str


class PhasePolicy(BaseModel):
    style: Literal["strict", "free"]
    tools_allowed: list[str] = Field(default_factory=list)
    disclosable: list[str] = Field(default_factory=list)
    must_ground: bool = False
    exits: list[Exit] = Field(default_factory=list)


class VerificationPolicy(BaseModel):
    required_fields: int = 3
    fields: list[str]
    mismatch_turns_offer_human: int = 3
    mismatch_turns_lock: int = 5
    unknown_policy_attempts: int = 2


class ScopePolicy(BaseModel):
    strikes_offer_human: int = 2
    strikes_handoff: int = 4


class Policy(BaseModel):
    name: str
    initial_phase: str = "VERIFY_ID"
    verification: VerificationPolicy
    scope: ScopePolicy = Field(default_factory=ScopePolicy)
    persuasion_budget: int = 2
    global_exits: list[Exit] = Field(default_factory=list)
    phases: dict[str, PhasePolicy]

    def phase(self, name: str) -> PhasePolicy:
        return self.phases[name]


def load_policy(name: str, verticals_dir: Path = VERTICALS_DIR) -> Policy:
    with (verticals_dir / f"{name}.yaml").open() as f:
        return Policy(**yaml.safe_load(f))


# --- predicate evaluator ------------------------------------------------------------
_PRED = re.compile(r"^\s*([A-Za-z_][\w.]*)\s+(==|!=|>=|<=|in|count>=)\s+(.+?)\s*$")


def _literal(s: str) -> Any:
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        return [_literal(x) for x in s[1:-1].split(",") if x.strip()]
    if s.lower() in ("null", "none"):
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s.strip("'\"")


def _lookup(state: dict, path: str) -> Any:
    cur: Any = state
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def evaluate(predicate: str, state: dict) -> bool:
    m = _PRED.match(predicate)
    if not m:
        raise ValueError(f"bad predicate: {predicate!r}")
    path, op, raw = m.groups()
    val, lit = _lookup(state, path), _literal(raw)
    if op == "==":
        return val == lit
    if op == "!=":
        return val != lit
    if op == ">=":
        return val is not None and val >= lit
    if op == "<=":
        return val is not None and val <= lit
    if op == "in":
        return val in lit
    if op == "count>=":
        return len(val or []) >= lit
    raise ValueError(op)
