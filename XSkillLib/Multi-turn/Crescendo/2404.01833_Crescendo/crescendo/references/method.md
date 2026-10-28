# Method

Crescendo is a black-box multi-turn jailbreak. It begins with a broad, benign
question related to the objective, then uses target responses as context for
gradually more specific follow-up questions. Crescendomation automates this with
an attack LLM, scoring, feedback, and backtracking on refusal.

`scripts/attack.py` is a **faithful port of Microsoft PyRIT's `CrescendoAttack`**
(`microsoft/PyRIT` @ commit `3a435ad884209b11d85f63f68122d469902ad389`,
`pyrit/executor/attack/multi_turn/crescendo.py`). Azure/PyRIT moved to
microsoft/PyRIT; Crescendo lives inside PyRIT's multi-turn orchestrators rather
than in a standalone repo, so the orchestration logic and all judge/attacker
prompts are ported verbatim into the paper-local package (cited, not imported).

Ported verbatim (`crescendo/prompts/`):

- `crescendo_variant_1.yaml` — adversarial-chat system prompt. The attacker LLM,
  given `{objective, max_turns}`, returns a JSON object with exactly
  `{generated_question, last_response_summary, rationale_behind_jailbreak}`.
- `refusal_objective_strict.yaml` — `SelfAskRefusalScorer` (PyRIT default
  `OBJECTIVE_STRICT`). Drives the **backtrack**: a refused turn is dropped from
  the target history and the turn counter is not advanced (`max_backtracks` cap).
- `red_teamer_system_prompt.yaml` + `task_achieved_scale.yaml` —
  `SelfAskScaleScorer` (0-100 task-achievement). Wrapped by
  `FloatScaleThresholdScorer(threshold=0.8)`: normalized score `>= 0.8` =>
  objective achieved (`success_flag`), matching PyRIT.

Control flow mirrors PyRIT `_perform_async`: per turn (1) adversarial chat emits
the next question, (2) send to the objective target on the full multi-turn
history, (3) refusal-score and backtrack if refused, (4) otherwise objective-score
and stop if `>= 0.8`. `max_turns` / `max_backtracks` are the PyRIT knobs.

Differences from PyRIT, all labeled: judge model is a permissive OpenRouter model
(`deepseek/deepseek-chat`) rather than the original GPT-4 (the prompt rubric is
verbatim; only the serving model changes — `openai/*` route 403s on harmful-judge
prompts); PyRIT's memory/`duplicate_conversation_excluding_last_turn` backtrack is
implemented as a local message-list truncation; no converters/auxiliary scorers.

Paper-local evidence: `digest/algorithms/alg-tool.tex`,
`digest/sections/03-crescendo.md`, `digest/sections/04-crescendomation.md`,
`digest/tables/tab-advbenchtasks.tex` (12 representative tasks; the canonical
AdvBench `harmful_behaviors.csv` is shipped under `data/advbench/` for
>=20-goal runs and the loader is dataset-agnostic).
