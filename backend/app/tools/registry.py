"""Tool registry and dispatch. Every guarantee here is enforced in code, independent of the
prompt: phase allowlist, tier authorization, argument validation, party ownership, consent."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from ..blackboard import Blackboard
from ..config import Settings
from ..policy import Policy

Tier = Literal["autonomous", "ask_first", "never"]


class ToolError(Exception):
    pass


@dataclass
class ToolCtx:
    bb: Blackboard
    store: Any            # the vertical's store (Store for insurance; duck-typed elsewhere)
    policy: Policy
    settings: Settings
    vertical: Any = None  # the vertical module (see app.verticals)


@dataclass
class ToolSpec:
    name: str
    tier: Tier
    args: type[BaseModel]
    fn: Callable[[ToolCtx, BaseModel], dict]
    description: str
    requires_verified: bool


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, *, tier: Tier, args: type[BaseModel], description: str = "", requires_verified: bool = False):
    def deco(fn):
        REGISTRY[name] = ToolSpec(name, tier, args, fn, description, requires_verified)
        return fn
    return deco


def _refuse(ctx: ToolCtx, name: str, reason: str) -> ToolError:
    ctx.bb.log("safety", event="tool_refused", tool=name, reason=reason, phase=ctx.bb.phase)
    return ToolError(f"{name}: {reason}")


def dispatch(ctx: ToolCtx, name: str, raw_args: dict | None = None, *, confirmed: bool = False) -> dict:
    bb, raw_args = ctx.bb, raw_args or {}
    spec = REGISTRY.get(name)
    if spec is None:
        raise _refuse(ctx, name, "unknown tool")
    if name not in ctx.policy.phase(bb.phase).tools_allowed:
        raise _refuse(ctx, name, f"not allowed in phase {bb.phase}")
    if spec.tier == "never":
        raise _refuse(ctx, name, "tier never")
    if spec.tier == "ask_first" and not confirmed:
        raise _refuse(ctx, name, "ask_first tool called without in-channel confirmation")
    if spec.requires_verified:
        if bb.verified_count < ctx.policy.verification.required_fields:
            raise _refuse(ctx, name, "caller not verified")
        if bb.identity.caller_role == "representative" and bb.post_process.consent.state != "approved":
            raise _refuse(ctx, name, "representative without approved consent")
    try:
        args = spec.args.model_validate(raw_args)
    except ValidationError as e:
        raise _refuse(ctx, name, f"invalid arguments: {e.errors()[0].get('msg')}")
    case_id = getattr(args, "case_id", None)
    if case_id is not None:
        rec = ctx.store.records_by_id.get(case_id)
        if rec is None or rec.party_id != bb.identity.resolved_party:
            raise _refuse(ctx, name, "case does not belong to the verified party")
    result = spec.fn(ctx, args)
    bb.log("tool", name=name, tier=spec.tier, args=args.model_dump(exclude_none=True), result=result)
    return result
