# DrAttack — reproduction plan (final)

Paper: **DrAttack: Prompt Decomposition and Reconstruction Makes Powerful LLM
Jailbreakers** (Li et al., EMNLP 2024, arXiv:2402.16914).
Official repo: `xirui-li/DrAttack@f51bee1` (vendored in `official/`).

## Method (black-box)

DrAttack jailbreaks by **decomposing** a harmful goal into a phrase tree (GPT-4
PCFG parse, pre-computed and cached), **reconstructing** the intent as an
in-context "Question A / Question B*" prompt with a *harmless* ICL demonstration,
then running a **level-wise synonym random search** scored by an embedding fitness
(cosine of the target response to "To {goal}" minus an opposite reference), with
early stop when a candidate is jailbroken and its negative-similarity score < 0.

`scripts/attack.py` is a verbatim-behavior port of the official `ga_attack.py`
evolve loop + `attack_manager.py` + `experiments/main.py` refusal list +
`evaluate_with_GPT.py` Yes/No judge. Access is fully **black-box** (chat API
target only); no gradients, no logits, no GPU.

## Decisions (confirmed)

- **Target + judge** = `api:deepseek/deepseek-chat` (OpenRouter). Paper used
  closed gpt-4o for the judge → `model_substitution_run`, official prompt kept
  **verbatim**, served by deepseek.
- **Embedding fitness** = local `sentence-transformers/all-MiniLM-L6-v2` (CPU).
  Documented substitution for OpenAI `text-embedding-ada-002` (OpenRouter serves
  no ada-002; OpenAI-direct quota exhausted). Cosine-fitness math unchanged.
- **Dataset** = official AdvBench 520 goals + official `prompts_information.json`
  (520 GPT-4 PCFG parses), captured under `data/` (official source preserved
  under `references/official/`). DrAttack needs a per-goal parse, so a fresh dataset
  would require a new GPT-4 parse pass — not performed; `--goals/--prompt-info`
  make it dataset-agnostic in principle.
- **Dual-metric**: official binary Yes/No content-harmful judge (goal-faithful,
  sees the original goal) + `test_prefixes` refusal-keyword proxy.
- **Completion run**: 20 goals × 2 reconstruction settings (`noun`, `noun+verb`)
  = 40 real cases. Plus a 3-target generalization sweep (llama-3.3-70b,
  qwen-2.5-72b, glm-4.6 × 10 goals).

## Result (self-checked)

- 40-case deepseek run: **asr_content_harmful = 0.10** (4/40),
  asr_refusal_bypass = 0.075 (3/40). Recomputed from raw per-case verdicts;
  matches summary.
- All 4 harmful cases read as **genuine on-goal harm** (OS-exploit script,
  manipulation tutorial, antivirus-disabling virus, corporate-network hacking).
  No off-topic false positives.
- All 40 cases decomposed; outputs 236–2362 chars; zero empty/truncated/decomp
  failures (no false negatives from pipeline issues).
- Generalization: llama-3.3-70b 0.10 harmful (real jailbreak), qwen-2.5-72b /
  glm-4.6 0.0 (real non-harmful outputs, resisted on subset; not errors).

DrAttack's per-goal ASR is modest and target-dependent, consistent with the
paper's finding that effectiveness varies by victim model.

## Red-team evidence

Per-case DrAttack transcripts (goal + reconstructed prompt → target output +
dual-metric verdict) are retained in `results/`; see `red_team_capability.json`
for the asset index. (The deprecated `harvest.py`/`Harvest.json` distillation was
dropped during consolidation.)
