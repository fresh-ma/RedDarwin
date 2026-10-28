# Code Plan: Contextual Interaction Attack

## Scope

Implement the paper's multi-turn attack artifact for real AdvBench goals:
`epsilon_1 ... epsilon_n`, pending target responses `alpha_i`, and the final
target question. Generation-only traces are input artifacts; Code completion
requires a live sequential target run that fills the target model's `alpha_i`
responses and final output.

## Analysis Ledger

- paper-core: owner=Codex; status=reviewed; evidence=
  `digest/sections/03.02-contextual-interaction-attack.md`,
  `digest/sections/03.03-design-choices.md`,
  `digest/sections/10-implementation-details.md`, and
  `digest/sections/16-auxillary-generation-prompts-and-hand-craft-examples-used-in.md`;
  conclusion=the attack uses an auxiliary LLM to generate benign-to-target
  `epsilon_i` questions, then uses the target model's own `alpha_i` responses
  as a context vector before asking the final target question.
- official-repo/report parity: owner=Codex; status=partial; evidence=
  `paper.meta.json`, paper digest sections, and `cia-context/scripts/attack.py`;
  conclusion=no official code URL is recorded locally (paperless; code_repos
  lists only the `openai/gpt-3` dependency). The Code preserves the verbatim
  appendix auxiliary prompt, AdvBench source goals, the multi-turn `[1,1]`
  target transcript shape with `alpha_i` feedback, decoding metadata, and the
  paper's dual judge — now driven by a LIVE auxiliary LLM (verbatim prompt), not
  deterministic ladders.
- implementation-risk: owner=Claude Code; status=resolved; evidence=
  `results/archive/cia_context_run_20260611_ready.json` and current script;
  conclusion=a clean 20-case live run (2 targets x 10 goals, 0 provider errors,
  2 parameter sets, recorded `max_tokens`/truncation) satisfies the gate.

## Decisions And Gates

| Gate | Current decision | Impact |
|---|---|---|
| Dataset | 10-row paper-local AdvBench subset | Real benchmark goals, small enough for local checks. |
| Auxiliary LLM | Live `deepseek/deepseek-chat`, verbatim §16 prompt | Substitutes WizardLM-70B (not served); prompt unchanged. |
| Target model | OpenRouter `llama-3.1-8b-instruct` + `qwen-2.5-7b-instruct` | Fills `alpha_i` and final output without targeting closed providers. |
| Judge | Dual: prefix-matching + verbatim PAIR GPT-4 (Rating==10) | Both reproducible paper judges; human judge left out. |
| Max tokens | `1024` per §10 | Multi-turn final outputs can be long; truncation recorded. |

## Completion Target — MET

20-case live run: refusal-bypass ASR 0.95, content-harmful ASR 0.00 (honest,
alignment-dependent; see `code/check.json` result_comparable). `overall=ready_to_use`.
