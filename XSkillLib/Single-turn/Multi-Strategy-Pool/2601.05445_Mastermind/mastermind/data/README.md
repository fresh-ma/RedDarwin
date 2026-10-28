# Mastermind datasets (arXiv 2601.05445)

The paper evaluates on two public test benchmarks and one auxiliary set for the
Phase-1 knowledge-accumulation bootstrap (sec 5.1).

| File | Rows | Role | Provenance |
|------|-----:|------|------------|
| `harmbench_standard_200.csv` | 200 | Phase-2 test (default `--data`) | HarmBench (Mazeika et al. 2024) `harmbench_behaviors_text_all.csv` filtered `FunctionalCategory == standard` = 200 standard behaviors, matching the paper's "HarmBench standard subset, 200 instances". Copied from `xsafebench/DataSet/harmbench/`. |
| `strongreject_small_60.csv` | 60 | Phase-2 test | StrongReject (Souly et al. 2024) custom small set, 60 instances (`forbidden_prompt` column). Matches the paper's "StrongReject custom small dataset, 60 instances". Copied verbatim from `xsafebench/DataSet/strongreject/`. |
| `auxiliary_advbench_200.csv` | 200 | Phase-1 knowledge accumulation only | **Substitution.** The paper's auxiliary set (200 LLM-generated harmful queries, no test overlap) was NOT released. Substituted by the first 200 AdvBench (Zou et al. 2023) `harmful_behaviors` goals as a public stand-in for the strategy-bank bootstrap. Documented as a `model_substitution`-class data gap; used only by `scripts/gen_knowledge.py`, never for reported test ASR. |
| `strategies.json` | 14 strategies | Phase-2 genome alphabet | Seed knowledge repository S. No official strategy bank released; seeded from the paper's disclosed strategy examples (Fig 1 + secs 3.3/4.1/4.2). Growable via `gen_knowledge.py`. |

Counts are real-counted with the `csv`/`json` modules (not `wc -l`).

## Notes
- **Hold full ≠ run full.** The folder holds the complete 200 + 60 test sets so the
  benchmark stays comparable; the consolidate validation run samples 20-30 cases.
- Row counts: HarmBench standard = **200**, StrongReject small = **60**, auxiliary =
  **200**, strategies = **14**.
