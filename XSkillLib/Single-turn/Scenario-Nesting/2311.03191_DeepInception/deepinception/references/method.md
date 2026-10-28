# DeepInception Method

DeepInception is a black-box, training-free prompt attack. Its core mechanism is
a nested fictional scene: each layer creates another scene, characters in each
layer discuss steps toward the goal, and the final instruction asks for a
layer-by-layer summary.

The self-contained runner implements the paper's template-only path, not the
later AutoInception extension. `render_deepinception_prompt` reproduces the
official `inception_attack` string **verbatim** from `res/data_main.json`
(commit `fc5689e`), including the paper's own grammatical quirks ("...to against
the super evil doctor", "...steps should used."). The goal is normalized exactly
as the official data is (`normalize_goal`: strip one trailing period, lowercase
the first character), which reproduces 39/50 official strings byte-for-byte; the
remaining 11 are hand-entry variants in the official JSON, not template-logic
differences. This keeps ASR comparable to the official runs. Default parameters
follow the paper:

- scene type: `science fiction` (paper also uses `stage scene`, `dream within
  dream`, `documentary`, `spy movie`)
- layers: `5` (layer ablation in the paper sweeps `1, 3, 5, 7, 10`)
- characters: `5`

Reference implementations consulted:

- Official repo: `https://github.com/tmlr-group/DeepInception` (commit `fc5689e`)
- Official dataset cached at `data/data_main_goals.json` (50 `plain_attack` goals)
- Paper digest: `data/papers/2311.03191_nested-scene-llm-jailbreak/digest/`

The runner intentionally drops paper-scale sweeps, multimodal image cases, and
AutoInception follow-up rounds. It keeps parameterized scene/layer/character
controls so small Code gates can exercise the main ablation axes.
