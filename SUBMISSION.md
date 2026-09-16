Subject: Insurance Claims SOP Agent — take-home submission

Live demo: https://insurance-sop-agent.onrender.com
Repo: https://github.com/vedanti02/insurance-sop-agent

The demo runs on a free-tier host, so the first request after ~15 idle minutes takes 30–60 seconds to wake. /api/health?probe=1 confirms the model provider is reachable.

To try it in two minutes: click "Demo: Margaret", then type "How long after I send them does it take?", then "What is reinforcement learning?", then "No, that's everything." and "Yes". The right-hand panel shows the phase, which identity fields matched (masked), the intent and case hint that were captured during verification and used after it, every tool call with its tier, and every guard event. "Angry caller" and "Injection" exercise the gates; the dropdown switches to a second vertical (card disputes) running on the same engine.

To run locally: copy .env.example to .env, set LLM_API_KEY (OpenAI), then `docker compose up --build`. `LLM_MODE=stub` runs the full engine without a key.

Design in one paragraph: the SOP lives in the harness, not the prompt. A YAML policy defines each phase's style, allowed tools, disclosable fields and exit predicates; the model writes facts into a blackboard (structured perception on every turn, which is what gives cross-phase memory) and the harness reads predicates off it. Identity verification is harness-driven and returns booleans only; claim tools cannot run before the gate opens because the registry enforces phase, tier, argument schema, party ownership and consent in code. A leakage validator hard-blocks account data the current caller may not hear; a grounding check soft-flags numbers not in the facts. Emotion and refusal are recognized per turn, de-escalation guidance is injected only when needed, and a persuasion budget decides when to stop persuading and offer alternatives or a human.

Evidence: 121 unit tests (no model); a 23-scenario live evaluation (12 golden, 11 adversarial) scoring trajectory, task, arguments, safety and LLM-judged naturalness — 23/23 on every level, naturalness 4.6–4.9/5; the card-disputes vertical passes 9/9 on the same suite. Cassettes let the suite replay offline. Every number in the README comes from that script.

Known limitations are stated in the README (caller text still reaches the model provider; fixture text is trusted; managed hosting does not apply the compose-level sandboxing).

Vedanti Kshirsagar
