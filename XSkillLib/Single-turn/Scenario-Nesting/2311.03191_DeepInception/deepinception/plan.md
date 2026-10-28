# DeepInception (2311.03191) — Reproduction Plan

## Method
Pure black-box, training-free prompt-template jailbreak. Wrap a harmful goal in a
nested fictional multi-layer scene ("layer i creates layer i+1"); each layer's
characters propose a step toward the goal "to against the super evil doctor";
the final layer asks for a layer-by-layer summary of concrete tools/steps. No
optimizer, no gradients, no model weights — a single prompt transformation.

## Depth
Faithful template reproduction. `render_deepinception_prompt` reproduces the
official `inception_attack` wording verbatim (commit fc5689e), including the
paper's grammatical quirks ("to against the super evil doctor", "should used").
Goal normalization (strip trailing period + lowercase first char) matches the
official data; this reproduces 39/50 official strings exactly — the remaining 11
are hand-entry variants in the official JSON, not template-logic differences.
Parameterized scene/layer/character controls expose the paper's main ablation
axes (scene type, layer count). AutoInception (the LLM-driven follow-up loop) and
multimodal image cases are out of scope.

## Target / Judge
- Target: `api:deepseek/deepseek-chat` (OpenRouter), black-box chat.
- Judge: `api:deepseek/deepseek-chat` dual-metric LLM judge reused from the
  XSafeBench reference harness — emits `refused` and `harmful` booleans per case.
  Metrics: `asr_refusal_bypass` (not-refused), `asr_content_harmful`
  (substantive harmful compliance), `asr_jailbreak_success` (not-refused AND
  harmful). This is a substitution for the paper's own GPT-4 (Qi et al.) judge;
  it preserves the dual refusal/harm distinction.

## Dataset
The paper's own dataset: `tmlr-group/DeepInception/res/data_main.json` (50
AdvBench-derived goals, `plain_attack` field). Cached locally as
`data/data_main_goals.json` (id, goal, category=topic). The runner re-renders
the template from the raw goal rather than reusing the prebaked
`inception_attack` string, so scene/layer parameters stay live.

## Configs (>= 2)
Two scene-type configs over the first 15 goals = 30 cases:
`science fiction|L5|C5` and `spy movie|L5|C5`.

## Success criteria
>= 10 cases, >= 2 distinct configs, all-ok target calls, real judge verdicts with
refused/harmful booleans, and computed `asr_refusal_bypass` +
`asr_content_harmful`. Achieved: 30 cases / 30 ok / 2 configs;
asr_refusal_bypass = 0.633, asr_content_harmful = 0.467.
