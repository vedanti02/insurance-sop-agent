Subject: Insurance Claims SOP Agent, take-home submission

Live demo: https://insurance-sop-agent.onrender.com
Repository: https://github.com/vedanti02/insurance-sop-agent

The demo runs on a free host. After 15 idle minutes the first request takes 30 to 60 seconds to wake. /api/health?probe=1 confirms the model provider is reachable.

To try it in two minutes: click "Demo: Margaret", then type "How long after I send them does it take?", then "What is reinforcement learning?", then "No, that's everything.", then "Yes". The panel on the right shows the phase, which identity fields matched, the intent and claim hints captured during verification and used after it, every tool call, and every guard event. The "Angry caller" and "Injection" buttons test the gates. The dropdown switches to a second workflow (card disputes) running on the same engine.

To run it locally: copy .env.example to .env, set LLM_API_KEY to an OpenAI key, then run `docker compose up --build`. `LLM_MODE=stub` runs the full engine without a key.

Delivery requirements: the hosted demo and the Docker and Render configuration cover deployment; .env.example accepts the model API token; the React chat UI is the text test surface; and the phase stepper, state inspector, trace, safety panel and email outbox show the complete VERIFY_ID, RESOLVE_INTENT, PROCESS_CASE, POST_PROCESS workflow.

To reproduce the offline evidence:

```bash
cd backend
.venv/bin/python -m pytest -q
LLM_MODE=stub .venv/bin/python tests/eval/run_eval.py --mode replay
```

Replay does not call the model provider; it uses recorded outputs and reports any that are missing. Live naturalness scores need LLM_API_KEY and `--mode live --judge`.

How it works, in short. The workflow lives in code, not in the prompt. A YAML file defines each phase's style, allowed tools, allowed fields and exit rules. On every turn one model call extracts a fixed set of signals from the caller's message (identity values, intent, claim hints, emotion, scope, yes or no, wants a human); the code stores them with the turn number, does the phase's work, evaluates the exit rules, and writes a directive saying what the reply must do and what facts it may use. A second model call turns the directive into speech. Identity checks run in code and return only true or false. Claim tools are refused by the registry until the gate is open. A leakage check blocks any reply containing account data the caller may not hear; a grounding check flags numbers not in the facts. Emotion is recognized every turn, de-escalation wording is added only when needed, and a two-point persuasion budget decides when to stop explaining and offer alternatives or a human.

Evidence. 121 unit tests with no model. A 23-scenario live evaluation (12 golden, 11 adversarial) scored on trajectory, task, tool arguments, safety and model-judged naturalness: 23 of 23 on every level, naturalness 4.6 to 4.9 out of 5. The card-disputes workflow passes 9 of 9 on the same suite. The first live run scored 18 of 23 and the README lists what the suite found and how each issue was fixed. Every number in the README comes from the evaluation script.

Every design decision is written up in the README with what was done and why, including the ones the fixture data forced: how many fields verify, why a wrong strong field fails a whole turn, why the ID type is never named, why phone matching is exact, how a representative gets consent, how claims are matched with a margin, how guidance is selected, why "diagnosis report" is not mapped to pathology guidance, and how a passed deadline overrides a template.

Limitations are also in the README: caller text still reaches the model provider, fixture text is trusted, the managed host does not apply the container hardening, and replies are not streamed.

Vedanti Kshirsagar
vedanti2202@gmail.com
