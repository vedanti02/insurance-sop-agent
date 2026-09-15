"""Append-only audit log, one JSON line per turn. PII masked by default. The demo keeps it on the
container's tmpfs for the container lifetime; production would ship it to a SIEM with a stated retention."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .blackboard import Blackboard, mask_pii

AUDIT_PATH = Path(os.environ.get("AUDIT_PATH", "/tmp/sop-audit.jsonl"))


def record(bb: Blackboard, phase_before: str, transitions: list[dict], models: dict[str, str]) -> None:
    turn_trace = [t for t in bb.trace if t.turn == bb.turn]
    entry = {
        "ts": time.time(), "session_id": bb.session_id, "turn": bb.turn,
        "phase_before": phase_before, "phase_after": bb.phase, "transitions": transitions,
        "tools": [{"name": t.data.get("name"), "tier": t.data.get("tier"), "args": t.data.get("args")}
                  for t in turn_trace if t.kind == "tool"],
        "validators": [t.data for t in turn_trace if t.kind == "validator"],
        "safety": [t.data for t in turn_trace if t.kind == "safety"],
        "llm": [t.data for t in turn_trace if t.kind == "llm"],
        "models": models,
        "usage": dict(bb.usage),
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a") as f:
            f.write(json.dumps(mask_pii(entry), default=str) + "\n")
    except OSError:
        pass  # a read-only filesystem must never break a turn


def purge(session_id: str) -> int:
    """Remove a session's audit lines (right-to-erasure for the demo). Returns lines removed."""
    if not AUDIT_PATH.exists():
        return 0
    lines = AUDIT_PATH.read_text().splitlines()
    keep = [ln for ln in lines if f'"session_id": "{session_id}"' not in ln]
    AUDIT_PATH.write_text("\n".join(keep) + ("\n" if keep else ""))
    return len(lines) - len(keep)
