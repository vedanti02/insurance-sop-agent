"""Vertical modules. Each exposes the same surface; the engine never imports a vertical directly.

    NAME, INTENTS, PROMPT_VARS, BINDINGS, SCRIPTS
    load_store() -> store with .policyholders/.by_party/.by_policy/.records_by_party/.records_by_id
    build_bundle(ctx) -> dict                 facts for PROCESS_CASE
    forbidden_terms(ctx) -> dict[str,set]     what the reply may not contain in the current phase
    post_process_directive(ctx, d) -> None    the offer / confirmation language for POST_PROCESS and CLOSED
"""
from __future__ import annotations

from importlib import import_module
from types import ModuleType

_REGISTRY = {
    "insurance_claims_v1": "app.verticals.insurance",
    "card_disputes_v1": "app.verticals.card",
}


def get(name: str) -> ModuleType:
    return import_module(_REGISTRY[name])


def names() -> list[str]:
    return list(_REGISTRY)
