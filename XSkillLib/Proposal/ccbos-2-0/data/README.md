# CC-BOS datasets

## Shipped (primary eval set)

- `advbench_harmful_behaviors.csv` — **AdvBench Harmful Behavior subset**, 520 rows,
  columns `goal,target` (zou2023universal, `Universal and Transferable Adversarial
  Attacks on Aligned Language Models`). This is the paper's primary evaluation
  benchmark (digest §4.1). The paper de-duplicates and selects **50 representative**
  requests for its main AdvBench experiment; the full 520 are shipped so the unit
  holds the complete set and stays comparable. **full_count = 520** (counted with the
  `csv` module, not `wc -l`).

The default loader (`cases.load_behaviors`) reads the `goal` column and also accepts
`Behavior` (HarmBench) / `prompt` / `text`, so the runner stays dataset-flexible.

## Paper's other datasets (not bundled)

The paper also evaluates on two more sets (digest §4.1), not shipped here because they
are competition / gated sets the official CC-BOS repo does not bundle either:

- **CLAS-2024** — 100 harmful queries (Competition for LLM and Agent Safety 2024,
  xiang2024clas).
- **StrongREJECT-small** — 60-question subset (souly2024strongreject).

To reproduce those slices, fetch the respective public releases and point `--dataset`
at a CSV/JSONL exposing a `goal`/`prompt`/`Behavior` column.

## Provenance

The official repo (`xunhuang123/CC-BOS`) bundles **no dataset** — its `data/data.md`
only cites AdvBench + CLAS-2024 + StrongREJECT-small externally (see
`ccbos/references/official/data/data.md`). AdvBench `harmful_behaviors.csv` here is the
canonical 520-goal release (llm-attacks/AdvBench).
