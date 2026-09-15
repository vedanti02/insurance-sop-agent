"""OpenAI-backed perceiver and responder. Two methods (structured, complete), a hard per-turn call
cap, usage/latency instrumentation, and safe fallbacks so a provider failure never drops the caller."""
from __future__ import annotations

import json
import logging
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel

from . import prompts, verticals
from .blackboard import Blackboard
from .config import Settings
from .directive import Directive
from .perceive import HeuristicPerceiver, Perception

log = logging.getLogger(__name__)


class CallCapExceeded(RuntimeError):
    pass


class OpenAIClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=40.0, max_retries=2)

    def _account(self, bb: Blackboard, kind: str, model: str, started: float, usage) -> None:
        ms = int((time.perf_counter() - started) * 1000)
        inp = getattr(usage, "prompt_tokens", 0) or 0
        out = getattr(usage, "completion_tokens", 0) or 0
        bb.usage["calls"] += 1
        bb.usage["input_tokens"] += inp
        bb.usage["output_tokens"] += out
        bb.usage["latency_ms"] += ms
        bb.log("llm", call=kind, model=model, input_tokens=inp, output_tokens=out, latency_ms=ms)

    def _check_cap(self, bb: Blackboard) -> None:
        if bb.model_calls_this_turn >= self.settings.max_model_calls_per_turn:
            bb.log("safety", event="model_call_cap", cap=self.settings.max_model_calls_per_turn)
            raise CallCapExceeded()
        bb.model_calls_this_turn += 1

    def structured(self, bb: Blackboard, model: str, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        self._check_cap(bb)
        started = time.perf_counter()
        r = self.client.chat.completions.parse(
            model=model, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema)
        self._account(bb, "perceive", model, started, r.usage)
        parsed = r.choices[0].message.parsed
        if parsed is None:
            raise ValueError("model returned a refusal or unparsable output")
        return parsed

    def complete(self, bb: Blackboard, model: str, system: str, user: str) -> str:
        self._check_cap(bb)
        started = time.perf_counter()
        r = self.client.chat.completions.create(
            model=model, temperature=0.4, max_tokens=400,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        self._account(bb, "respond", model, started, r.usage)
        return (r.choices[0].message.content or "").strip()


PROVIDER_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError, CallCapExceeded, ValueError)


class LLMPerceiver:
    def __init__(self, client: OpenAIClient):
        self.client = client
        self.fallback = HeuristicPerceiver()

    def perceive(self, text: str, bb: Blackboard) -> Perception:
        vertical = verticals.get(bb.vertical)
        last_agent = next((m.text for m in reversed(bb.history) if m.role == "agent"), None)
        options = [c for c in bb.intent.candidate_cases if c["case_id"] in bb.control.pending_options]
        ctx = {"phase": bb.phase, "pending_question": bb.control.pending,
               "pending_options": [{"case_id": c["case_id"], "label": c["label"]} for c in options],
               "agent_last_said": last_agent}
        user = f"CONTEXT: {json.dumps(ctx)}\n\n<caller>{text}</caller>"
        try:
            p = self.client.structured(bb, self.client.settings.perceive_model, prompts.perceive_system(vertical), user, Perception)
            return p.clamped(vertical.INTENTS)  # type: ignore[union-attr]
        except PROVIDER_ERRORS as e:
            log.warning("perceive fallback: %s", e)
            bb.log("info", event="perceive_fallback", error=type(e).__name__)
            return self.fallback.perceive(text, bb).clamped(vertical.INTENTS)


class LLMResponder:
    def __init__(self, client: OpenAIClient):
        self.client = client

    def respond(self, bb: Blackboard, d: Directive) -> str:
        if d.canned:
            return d.canned
        vertical = verticals.get(bb.vertical)
        system = prompts.respond_system(vertical, d.phase)
        tail = "\n".join(f"<{m.role}>{m.text}</{m.role}>" if m.role == "caller" else f"agent: {m.text}"
                         for m in bb.recent(6)[:-1])
        directive = d.model_dump(exclude={"canned"}, exclude_none=True)
        user = (f"DIRECTIVE:\n{json.dumps(directive, default=str)}\n\n"
                f"RECENT CONVERSATION:\n{tail or '(start of call)'}\n\n"
                f"CALLER JUST SAID:\n<caller>{bb.control.last_utterance}</caller>")
        try:
            return self.client.complete(bb, self.client.settings.respond_model, system, user) or prompts.safe_fallback(vertical, d.phase)
        except PROVIDER_ERRORS as e:
            log.warning("respond fallback: %s", e)
            bb.log("info", event="respond_fallback", error=type(e).__name__)
            return prompts.safe_fallback(vertical, d.phase)
