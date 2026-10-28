# Datasets — DeepInception (2311.03191)

The paper (Sec 4.1, Experimental Setups) evaluates on two black-box jailbreak
benchmarks:

> "Following previous works on adversarial jailbreak, we evaluate methods on the
> 'harmful behaviors' in the AdvBench benchmark, which contains 520 objectives
> that request harmful content from different topics ... We also provide a
> comparison of the full version of the benchmark in Table [tab:full_advbench].
> In addition, we also validate it on Jailbench, which contains diverse
> behaviors that are against the OpenAI's usage policies."

## advbench_harmful_behaviors.json — PRIMARY (full 520)

- What: the complete AdvBench "harmful_behaviors" set — 520 unique harmful
  objectives. This is the dataset DeepInception's main results are reported on
  (the paper's Table `tab-full-advbench` is the full version; the PAIR/ART
  "remove repeated requests" subset is a curated slice of the same 520).
- Rows: 520 (all goals textually unique).
- Fields per row: `id`, `goal`, `target`, `category` (category empty — AdvBench
  ships no category column; kept for schema parity).
- Source: canonical Zou et al. 2023 `llm-attacks` AdvBench
  `data/advbench/harmful_behaviors.csv` (`goal,target`), md5
  `600961b912729bf6da03d7087d63f063`, cached at
  `.workspace/external/flipattack-official/data/harmful_behaviors.csv`
  (byte-identical to NJUNLP/ReNeLLM copy). Converted CSV -> flat JSON list.

## jailbreakbench_behaviors.json — ADDITIONAL named benchmark (100)

- What: JailbreakBench (Chao et al. 2024) "harmful-behaviors" — 100 behaviors
  against OpenAI usage policy, the "Jailbench" the paper cross-validates on.
- Rows: 100.
- Fields per row: `id` (Index), `goal` (Goal), `target` (Target),
  `category` (Category), `behavior` (Behavior), `source` (Source).
- Source: JailbreakBench `harmful-behaviors.csv`, cached at
  `data/papers/.../xwlin-roy__ICON/data/raw data/JailbreakBench/harmful-behaviors.csv`.
  Converted CSV -> flat JSON list.

## Why the old slice was removed

The previous `data_main_goals.json` (50 rows) was the official repo's demo
subset `res/data_main.json` `plain_attack` field — a 50-row curated subset of
AdvBench (42/50 match AdvBench verbatim; the rest differ only in
whitespace/punctuation). The repo ships only demo subsets (5–50 rows), not the
full benchmarks the paper reports on, so the complete AdvBench/JBB are obtained
from their canonical sources above. No slice/sample dataset files remain.

`attack.py` `load_dataset` reads the `goal`/`Goal` field, so both JSON files
load directly. `DEFAULT_DATASET` points at the full AdvBench 520.
