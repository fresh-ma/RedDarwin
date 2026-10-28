# Datasets — humor jailbreak (2504.06577)

The paper (Sec 4) evaluates on three public harmful-request sets. All three are held
here in full (the paper's complete experimental set), default = AdvBench.

| file | paper name | rows | source / provenance |
|---|---|---|---|
| `advbench_harmful_behaviors.json` | D2 AdvBench | 520 | Zou et al. 2023 (llm-attacks `data/advbench/harmful_behaviors.csv`, MIT). Byte-identical to the repo canonical copy `xsafebench/DataSet/advbench/`. |
| `jbb_harmful_behaviors.json` | D1 JBB | 100 | JailbreakBench behaviors (Chao et al. 2024). From the unit `intake/data/jailbreakbench_harmful_behaviors.csv` (`Goal` column). |
| `hexphi_harmful_behaviors.json` | D3 HEx-PHI | 300 | HEx-PHI (Qi et al. 2024), 10 public category files x 30 (category 2 intentionally withheld upstream; 300 matches the paper's D3 denominator). From `intake/data/hex-phi/category_*.csv`. |

None of these were produced by this paper — they are adopted public benchmarks. A goal
is inserted VERBATIM (word-by-word) into the humor template; no rewriting/decomposition.
