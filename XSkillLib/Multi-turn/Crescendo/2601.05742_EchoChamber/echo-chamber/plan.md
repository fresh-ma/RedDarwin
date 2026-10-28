# Echo Chamber Code Plan

Paper: `2601.05742_echo-chamber-escalation-jailbreak`
Method: `echo-chamber`
Date: 2026-06-22

## Benchmark Unit

Echo Chamber is a black-box multi-turn jailbreak. It starts with disguised
poisonous/steering seeds, asks the target to generate several possible paths,
selects a promising path, then repeatedly asks subtle follow-up questions that
amplify the target model's own previous output.

## Source Check

Official repo: `NeuralTrust/echo-chamber`.

The public repo includes the attacker prompt, seed generation prompt, path
selection prompt, answer/objective evaluators, secondary judge, OpenAI/Gemini
clients, and the 12-task AdvBench subset used in the paper. The paper-local
runner copies the official task file to `data/adv-bench.json`
and reimplements the loop without importing the official package as a runtime
dependency.

## Analysis Ledger

- paper-core: Codex; status `implemented`. Evidence:
  `digest/sections/03-echo-chamber-attack.md`,
  `digest/sections/04.01-overview.md`, and official `echo_chamber/attack.py`.
  Conclusion: the core is an attacker-target-judge multi-turn loop with seed
  generation, path selection, persuasion turns, and secondary LLM evaluation.
- official-repo/report parity: Codex; status `partial`. Evidence: official repo
  uses Gemini/GPT-family attacker/target/judge models and beta structured output
  parsing. Conclusion: runner preserves role/prompt structure but substitutes
  OpenRouter open/lab models.
- implementation-risk: Codex; status `known`. Evidence:
  `code_knowledge/logistics.md` model policy and paper section 4.2. Conclusion:
  the result is `partial_algorithm_code` and `model_substitution_run`, not a
  paper metric parity claim.

Full-run status: `external_staging_not_required`. This is an API black-box run
with no local weights, CUDA, Deakin, Vast, Docker, or model-cache requirement.

## Run Target

Fast validation uses:

- target: `api:deepseek/deepseek-chat`
- attacker: `api:deepseek/deepseek-chat`
- judge: `api:deepseek/deepseek-chat`
- sample: 10 of the official 12 AdvBench objectives
- max turns: 4 for the quick benchmark run

Results are saved to
`results/echo_chamber_deepseekchat_n10_20260622.json`.
