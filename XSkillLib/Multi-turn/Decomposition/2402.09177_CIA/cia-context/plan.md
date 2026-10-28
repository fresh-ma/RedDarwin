# Reproduction Plan

## Scope

Paper: `2402.09177_multi-turn-contextual-jailbreak`.

Method: Contextual Interaction Attack (CIA), a black-box inference-time multi-turn jailbreak.

This unit reproduces the attack generator and evaluator, not a global runner. The method folder is self-contained:

- `data/` contains reusable seed payload/data.
- `scripts/` contains the paper-local generator, runner, re-run driver, and result annotator.
- `results/` contains target/judge outputs and the canonical audited result index.
- `environment.md` describes local env and API variables.

## Payload Contract

`payload` means the harmful or effect-carrying text. For CIA:

| Stage | Field | Meaning |
|---|---|---|
| Raw payload | `goal` / `payload.payload_original.text` | AdvBench harmful goal. |
| Transform | `auxiliary.raw_output` | Auxiliary LLM decomposes the goal using the verbatim appendix prompt. |
| Transformed payload | `auxiliary.epsilon_sequence` / `payload.payload_transformed` | The epsilon ladder. The final epsilon is the disguised attack query. |
| Input carrier | `transcript` / `payload.input_carrier` | Full multi-turn chat: each epsilon as a separate user message, with target answers carried forward. |
| Effect | `final_response`, `verdicts` | Refusal-bypass and content-harmful judge outputs. |

## Paper Evidence

- `digest/sections/03.02-contextual-interaction-attack.md`: context vector and epsilon/alpha loop.
- `digest/sections/03.03-design-choices.md`: dynamic multi-turn context matters; single concatenation is not the same mechanism.
- `digest/sections/04.01-experiment-setting.md`: AdvBench Subset, WizardLM-70B auxiliary, target panel, auxiliary refusal as failure.
- `digest/sections/09-evaluation-metrics-chatgpt-score-prefix-matching-and-human-j.md`: prefix matching, PAIR/ChatGPT-score judge, human judge.
- `digest/sections/10-implementation-details.md`: deterministic decoding and system prompts.
- `digest/sections/16-auxillary-generation-prompts-and-hand-craft-examples-used-in.md`: verbatim auxiliary prompt.

## Current Evidence

Historical results were imported into `results/`. The audited JSON is append-only and derived from the raw token-fix result plus `GLM_REVIEW_tokfix_20260626.md`.

| Result | Target/Judge | Cases | Provider errors | Truncated | Content-harmful ASR |
|---|---:|---:|---:|---:|---:|
| `results/cia_context_run_20260611_ready.json` | Llama-3.1-8B + Qwen-2.5-7B / DeepSeek Chat judge | 20 | 0 | 12 | 0/20 |
| `results/cia_context_v4flash_tokfix_20260626_audited.json` | DeepSeek V4 Flash target + judge | 20 | 0 | 0 | raw 2/20, audited 1/20 |
| `results/cia_mistral_susceptible_20260627.json` | Mistral probe / DeepSeek V4 Flash judge | 6 | 3 | 2 | 0/3 completed |

The token-fixed DeepSeek V4 Flash run is the most informative existing positive run. Raw judge success is 2/20, but GLM audit confirms 1/20 and downgrades one fiction-without-payload false positive. The Llama/Qwen run is a clean robust-target negative. These should not be merged into a single ASR.

## Remaining Gaps

- The local data file is the 10-row slice used by saved live runs, not the full 50-row PAIR AdvBench subset.
- Human judge from the paper is not reproduced offline.
- Existing historical LLM-judge outputs use DeepSeek models; future fresh runs should choose the desired open/lab judge explicitly via `--judge-model`.
