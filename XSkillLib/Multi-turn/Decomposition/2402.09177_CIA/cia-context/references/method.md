# Method Reference - Contextual Interaction Attack

The paper defines a context vector `c = {ε₁, α₁, …, εₙ, αₙ}`. The preliminary
inputs `εᵢ` are individually harmless and progressively approach the goal; the
**last** `εᵢ` is a sensitive-word-free paraphrase of the goal and is the actual
attack query. An **auxiliary LLM** generates the `εᵢ` from three hand-crafted
demonstrations via in-context learning (verbatim appendix prompt). Each `εᵢ` is
posed to the target in a **separate turn** (`[1,1]` schedule); the target's own
answer `αᵢ` is carried forward as context. The final answer is the attack
output. Default `n = 2` -> 3 prompts (2 preliminaries + 1 disguised query).

## Payload boundary

- Raw payload: the AdvBench row field `goal`.
- Transformed payload: `auxiliary.epsilon_sequence`; the last epsilon is the
  sensitive-word-free target-facing attack query.
- Input carrier: the full multi-turn `transcript`, not a single prompt string.
  Each epsilon is sent as its own user turn and the target's prior `alpha_i`
  response is carried forward.

Every new `scripts/attack.py run` output stores this under
`payload.contract == payload_trace.v1`.

## Pipeline (`scripts/attack.py run`)

1. `auxiliary_generate` - verbatim §16 prompt -> OpenRouter open model ->
   `parse_epsilons` extracts the numbered prompt list. Auxiliary refusal (or a
   degenerate list) is counted as an attack failure, per §4.1.
2. `run_target_conversation` - pose each `epsilon_i` sequentially, feeding `alpha_i` back.
3. dual judge on the final response (see `evaluation.md`).

Decoding: `temperature 0`; the paper used `max_tokens 1024`, while the current
default is `2048` because the historical 1024-token run truncated 14/20
multi-turn outputs. The token-fix result records this substitution.

## Substitutions (documented)

- **Auxiliary LLM**: paper uses WizardLM-70B; not served on OpenRouter, so we use
  an open instruct model. The auxiliary only needs in-context decomposition
  ability; the verbatim prompt is unchanged.
- **Target**: project open/lab panel on OpenRouter (no GPT/Claude/Gemini
  targeting; see `code_knowledge/logistics.md`).

Historical saved results also include DeepSeek V4 Flash as target and judge.
Keep those as model-substitution provenance; fresh runs should set every model
role explicitly.

## Source Evidence

- `digest/sections/03.02-contextual-interaction-attack.md`
- `digest/sections/03.03-design-choices.md`
- `digest/sections/04.01-experiment-setting.md`
- `digest/sections/04.05-ablation-study.md`
- `digest/sections/09-evaluation-metrics-chatgpt-score-prefix-matching-and-human-j.md`
- `digest/sections/10-implementation-details.md`
- `digest/sections/16-auxillary-generation-prompts-and-hand-craft-examples-used-in.md`
