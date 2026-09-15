"""Responder protocol plus the offline stub used by tests and key-less demos."""
from __future__ import annotations

import json
from typing import Protocol

from .blackboard import Blackboard
from .directive import Directive


class Responder(Protocol):
    def respond(self, bb: Blackboard, d: Directive) -> str: ...


class StubResponder:
    """Renders the directive deterministically. No language model."""

    def respond(self, bb: Blackboard, d: Directive) -> str:
        if d.canned:
            return d.canned
        parts = [f"[{d.phase}] {d.goal}"]
        if d.facts:
            parts.append("facts: " + json.dumps(d.facts, default=str)[:600])
        if d.ask:
            parts.append(f"(asks: {d.ask}{' ' + ', '.join(d.options) if d.options else ''})")
        return "\n".join(parts)
