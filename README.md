# Insurance Claims SOP Agent

A customer-service agent that follows a fixed business workflow — **VERIFY_ID → RESOLVE_INTENT → PROCESS_CASE → POST_PROCESS** — while conversing naturally. The SOP lives in the harness, not in the prompt: the model writes facts, the harness reads predicates, and the gates open on state, never on model output.

Two verticals run on the same engine with zero engine changes between them — insurance claims (the assignment) and card disputes (a structurally different workflow added to prove the abstraction). Both pass the same evaluation suite; numbers below.

## Live demo

**https://insurance-sop-agent.onrender.com** — free-tier host, so the first request after ~15 idle minutes takes 30–60 s to wake; `/api/health?probe=1` confirms the model provider is reachable. Pick the vertical in the top-left dropdown; the quick buttons paste the scripted callers.

## Sixty-second quickstart

```bash
git clone <this repo> && cd insurance_claims
cp .env.example .env            # put your OpenAI key in LLM_API_KEY
docker compose up --build       # http://localhost:8000
```

Paste this as the caller:

> I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.

Then try: *"How long after I send them does it take?"* → *"No, that's everything."* → *"Yes please."* The right-hand panel shows the phase, which identity fields matched (masked), the intent and case hints that were remembered during verification, every tool call with its tier, every validator verdict, and the mock email outbox.

No key? `LLM_MODE=stub docker compose up` runs the same engine with a regex perceiver and a template responder — every gate, every guard, no model.

Without Docker: `cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn app.main:app --port 8000` (serves the UI from `frontend/dist` if you ran `npm run build` in `frontend/`).

## The core idea

Two things decide what the agent says on any turn:

1. **The harness** (deterministic Python, no model): owns the phase, the identity gate, consent, which claim is open, scope strikes, the persuasion budget, and which tools exist. It reads a YAML policy per phase and emits a *directive*: the goal for this turn, the facts the model may state, what it must not do, the tone, and the question to end on.
2. **Two model calls per turn**: *perceive* (structured extraction: identity candidates, intent, case hints, emotion, scope, yes/no, "I want a human") and *respond* (turn the directive into speech). Neither call can advance a phase, open a gate, read a claim, or send an email — those are harness actions on blackboard state.

The freedom dial per phase, from `verticals/insurance_claims_v1.yaml`:

| Phase | Style | Model may state | Harness decides |
|---|---|---|---|
| VERIFY_ID | strict | nothing about the account — the disclosable list is empty | which fields matched, attempts, lockout, representative + consent |
| RESOLVE_INTENT | free | claim type, month/year, status | candidate scoring, ambiguity → ask, unique → proceed |
| PROCESS_CASE | free | the open claim's record + selected guidance | which guidance templates, document alternatives, deadline precedence |
| POST_PROCESS | strict | the drafted summary | drafting from the blackboard, send only on an explicit yes, recipient from the record |

**Cross-phase memory** is a consequence of running perceive on every turn in every phase: "I'm calling about my denied healthcare claim from January" said during verification is stored with its turn number and marked *deferred*; the machine stays in VERIFY_ID; the moment the gate opens, case matching runs on the stored hints and the reply says "I see you're calling about your healthcare claim from January, I'm pulling that up."

## Decisions the fixtures forced

| Question | Decision |
|---|---|
| What verifies | ≥3 of {full name, DOB, phone, email, ID last 4} matching one record. A policy number *resolves* a record and never counts. Aliases in the fixtures count. |
| One wrong field among four | A wrong **strong** field (ID last 4, phone, email) fails the whole turn — nothing is credited. A weak-field miss (name/DOB typo, ASR noise) still credits the rest. Never say which value was wrong. Never confirm an account exists. |
| Attempts | Counted per mismatched **turn**, not per field. 3 → offer a human; 5 → locked, gate closed, no data. Already-verified fields are never re-evaluated (a first name echoed from context must not count as a miss). |
| `id_type` | One generic `id_last4` field. The agent asks for "the last four of the ID on your policy" and accepts "SSN" from a caller whose record says national ID. |
| Phone | Exact last-10-digit equality. P9 ends …2836 and P13 ends …2830; no prefix or fuzzy matching. |
| Representative (`representatives.json`) | Name on the record is the key; the stated relationship is informational (callers say "her son" or "my mother"). Needs the policyholder's 3 fields **and** consent: `request_consent` then polls `check_consent_status` over `consent_scenarios.json` — `default` approves on the second poll, `timeout` never does → not authorized, alternatives offered, clean close. |
| Email summary | Explicit in-channel yes/no. `send_summary_email(session_id)` takes no recipient; it is resolved from the record server-side, so "send it to attacker@evil.com" is an unreachable code path. |
| Document names | Claims say "pathology report"; guidance is keyed "original pathology report". A static alias map + token containment resolves both of CL-2048's; "diagnosis report" (CL-3001) resolves to nothing and gets the default guidance rather than being snapped to pathology. `python -m app.data.check` prints exactly this. |
| Follow-up templates | Selection mirrors the file: `intent_hints` ∧ `requires_documents` ∧ longest `match_any` phrase; entries without `match_any` by intent alone; else the fallback. Claims without `documents_needed` only ever get the fallback. |
| Deadline | `DEMO_TODAY` (default 2026-03-01; the real date is past both fixture deadlines). Precedence: claim record > document guidance > topic template > case-type > default. A passed `appeal_deadline` suppresses "submit within a week" and routes to human review. |
| Money | `net_pay` is what was paid; `allowed_max_amount` is a cap, never "owed". CL-2048 shows 0.00 against 1450.00 and the directive says so. |
| Scope | Three-way. Out of scope → decline, redirect, strike (2 → offer a human, 4 → handoff). In scope but ungrounded → say so, offer a human, **no strike**. Injection is a subtype of out-of-scope plus a safety event. |
| Emotion (bonus) | De-escalation guidance is injected only when perceive reports anger/frustration/refusal. A persuasion budget of 2: each "why verification matters" decrements it; at 0 the agent stops persuading and offers alternatives (another field, callback, human); the next negative turn escalates. The counter is visible in the trace. |

## Two verticals, one engine

A vertical is a YAML policy plus one Python module (`app/verticals/<name>.py`) that supplies: the store, the intent list and prompt vocabulary, five tool *bindings* (list / resolve / record / summary / finish), a bundle builder for PROCESS_CASE, a forbidden-terms builder for the leakage guard, and the post-process offer language. The engine — turn loop, machine, memory, verification, guards, tool dispatch — does not import either vertical.

| | Insurance claims | Card disputes |
|---|---|---|
| Verification | 3 of 5 fields | 2 of 5 fields (`required_fields: 2`) |
| Resolving the record | type + status + month/year | merchant token overlap + amount within 1% + month/year |
| Consent shape | policyholder consent for a representative; email summary yes/no | provisional-credit acknowledgment: an `ask_first` tool that runs only on an explicit yes |
| Deadline | `appeal_deadline` overrides "within a week" | `dispute_window_ends` overrides "you can still send evidence" |
| Fixtures | `fixtures/` (given) | `verticals/card_disputes/` (3 cardholders, 4 disputes, small guideline) |
| Added code | — | 30-line YAML, ~140-line tool file, ~150-line vertical module, 9 scenarios |

Switch with the dropdown in the UI or `VERTICAL=card_disputes_v1`. Try: *"Hi, this is Priya Natarajan, date of birth June 21 1988. I'm calling about my dispute with Skyline Electronics."*

What leaked while building it, honestly: the `CaseHints` schema grew two fields (`merchant`, `amount`) that insurance ignores; the regex fallback perceiver is insurance-only (a key-less demo of the card vertical runs the engine but not the language); and the representative flow is skipped when a store has no `representatives` table rather than being a vertical hook.

## Safety architecture

**Information flow.** No value from `policyholders.json` ever enters a prompt. Verification returns booleans. Claim data cannot be in the model's context before the gate opens because the claim tools are not callable: the registry enforces a per-phase allowlist, a tier (`autonomous` / `ask_first` / `never`), argument schemas with `extra="forbid"`, `claim.party_id == verified_party`, and consent for representatives — in code, before any function runs, regardless of what the prompt or the caller says. There is no `advance_phase` tool and no code-execution tool; the action space is the fixed typed tool set.

**Output validators.** Leakage is a hard block: a forbidden set is built from every claim and every policyholder the current caller may not hear about (case ids, amounts in several spellings, dates in several spellings, 4-word shingles of denial reasons and summaries, document names, names, emails, phones, DOBs), minus what the caller themselves already said. A hit logs a redacted safety event, regenerates once with the reason appended to `must_not`, then falls back to a canned reply. Grounding is a soft check in `must_ground` phases: numbers in the reply must exist in the facts bundle; a miss is a trace warning, not a block — a leakage false positive costs a stiffer sentence, a grounding false positive would ruin the demo. `tests/test_redteam.py` drives these with a deliberately leaky responder so the guards, not the model, are under test.

**Credentials and sandbox.** The model key is env-only; `.env` is gitignored; startup fails loudly in live mode without it. The container runs as a non-root user with a read-only filesystem, tmpfs `/tmp`, fixtures and policy mounted read-only, a hard cap of 3 model calls per turn, and 40 s provider timeouts with two retries and a caller-facing fallback rather than a dropped call.

**Monitoring.** Every turn appends one masked JSON line to the audit log (session, turn, phase before/after, predicate that fired, tools + args + tier, validator verdicts, safety events, model/tokens/latency). `DELETE /api/sessions/{id}` purges the session and its audit lines. The UI's trace tab is the same data, per turn.

## Evaluation

From `backend/`, `python tests/eval/run_eval.py --mode live --judge [--vertical card_disputes_v1]` runs the scripted scenarios against the real model, records cassettes, and scores five levels; `LLM_MODE=stub python tests/eval/run_eval.py --mode replay` reruns them offline and free. Replay reports any cassette misses and uses the local fallback rather than contacting a model provider. Safety is pass/fail on the whole suite.

Latest live runs (gpt-4.1-mini perceive, gpt-4.1 respond):

| Level | Insurance (12 golden + 11 adversarial) | Card disputes (5 golden + 4 adversarial) |
|---|---|---|
| Trajectory (phases per turn) | 23/23 | 9/9 |
| Task (record, state, expected content) | 23/23 | 9/9 |
| Arguments (no invalid tool calls) | 23/23 | 9/9 |
| Safety (no forbidden text, no refused tools) | 23/23 — PASS | 9/9 — PASS |
| Naturalness (LLM judge, golden only, 1–5) | 4.6–4.9 across four runs | 4.8–5.0 across two runs |
| Latency | ~1.2–1.6 s per model call, 2 calls per turn (3 with a regeneration) | same |

Golden: Margaret happy path; identity split over three turns with the hint remembered; ambiguous "healthcare claim from January" → disambiguation (CL-2048 vs CL-2011); "Yaven Li" alias with alias email and no claims; Ava Lopez with no claims; David Chen with consent approved and with consent timeout; Ma Tian through document alternatives to human review; email declined; multi-case switch without re-verification; the brief's literal angry caller; a passed appeal deadline.
Adversarial: cold "why was my claim denied"; instruction override; fake SYSTEM message; asserted prior state; DOB oracle probe; ID guessing to lockout; "print your system prompt"; another party's case id while verified; an unlisted husband; out-of-scope ×3; email redirection.

Unit tests (`pytest`, 121, no model): normalizers (aliases, day/month ambiguity, spoken digits, spelled names, phone collision), verification policy, predicate evaluator, state machine incl. the re-entry edge, guidance selection and rendering, consent branches, the leaky-responder red team, the emotional-recovery bonus, the audit log, and the card vertical on the same engine.

The first live run scored 18/23 on task. The suite found: a rep flow that failed because the perceiver reported the relationship from the other side; a first name re-extracted from context counted as a mismatch; the out-of-scope decline being overwritten by the phase builder; "I can't get anything from them" not mapping to the outstanding documents; the CLOSED phase swallowing the "email sent" confirmation; and, after the vertical refactor, a YAML value `none` that the predicate parser read as null and closed every call early. All fixed and re-measured; nothing in this README was typed by hand.

## Repository

```
verticals/insurance_claims_v1.yaml   phase policy: style, tools, disclosable, exit predicates, budgets
verticals/card_disputes_v1.yaml      the second vertical's policy (+ card_disputes/ fixtures)
backend/app/
  verticals/     insurance.py, card.py — store, intents, prompt vocabulary, bindings, bundle, forbidden terms, offer
  policy.py      YAML loader + 20-line predicate evaluator (==, !=, >=, <=, in, count>=; no eval)
  machine.py     one step at a time so harness work runs between hops
  turn.py        perceive → absorb → [act → gate]* → directive → respond → validate → commit
  perceive.py    Perception schema (strict JSON), heuristic fallback
  memory.py      cross-phase absorb with provenance
  verify.py      harness-driven verification, resolution ≠ verification, representative check
  normalize.py   the fixtures' difficulty: aliases, dates, phones, spoken digits, spelled names
  cases.py       joint scoring on type/status/month/year, margin-based disambiguation
  guidance.py    bundle: claim + document requirements/alternatives + selected templates + deadline rule
  tools/         registry with tier/phase/ownership/consent enforcement; the tool implementations
  validate.py    leakage (hard) and grounding (soft)
  llm.py         OpenAI perceive/respond, call cap, instrumentation, fallbacks
  prompts.py     all model-facing language
  audit.py       append-only masked audit log + purge
backend/tests/   unit tests, red team, eval/ (scenarios.yaml, run_eval.py, cassettes/)
frontend/        React chat + inspector (state / trace / outbox)
```

## Known limitations

- Caller utterances still reach a third-party model provider, so PII minimization is partial (fixture PII never does).
- Fixture text is trusted. Production upstream text (claim notes, guidance) would need the same untrusted-input handling as caller speech.
- The read-only filesystem, non-root user and tmpfs are enforced by `docker-compose.yml`; a managed host (Render/Fly) honors the image's user but not the compose hardening, and there is no egress allowlist without a network policy.
- Verification progress is acknowledged ("your name and date of birth match"), which is standard for call centers but is a one-bit oracle per field; the defenses are the strong-field rule and the 5-turn lockout, not secrecy of progress.
- Consent polling is synchronous ticks over the fixture sequence, shown in the trace, not a real async service.

## What another week would buy

Streaming replies; a real consent service and email/credit provider behind the same tools; per-field rate limiting across sessions (policy-number enumeration is currently bounded only per session); an LLM judge for groundedness to complement the numeric check; a representative hook in the vertical protocol; and a second perceiver fallback that is vertical-aware.
