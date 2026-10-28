# S2C data

## `jbb_behaviors_full.csv` (100 goals) — FULL dataset (default for canonical runs)

The paper's primary public evaluation set: **JBB-Behaviors** (JailbreakBench, Chao et al. 2024),
100 distinct misuse behaviors spanning 10 categories (Disinformation, Economic harm, Expert advice,
Fraud/Deception, Government decision-making, Harassment/Discrimination, Malware/Hacking, Physical harm,
Privacy, Sexual/Adult content). Materialized in full from the JailbreakBench behaviors CSV cached in-repo.
Columns: `id, goal, target, category`. This is the `red_team_capability.json.data` full set
(`full_count = 100`). The 2026-07 canonical runs sample 20 rows from it. The paper also uses the
**HarmBench** standard subset (200) — a second public set not bundled here; pass its CSV via `--data`.

## `s2c_seed_behaviors.csv` (25 goals)

Default seed set for the Structured Semantic Cloaking reproduction. The paper
(arXiv 2603.16192) evaluates on two public benchmarks it does **not** redistribute:

- **JBB-Behaviors** (Chao et al., 2024) — 100 distinct misuse behaviors.
- **HarmBench** standard subset (Mazeika et al., 2024) — 200 malicious queries.

No official code or seed file was released with this paper, so this 25-row set is a
**generated seed** for wiring + a real `--sample` run. It covers the misuse
categories the two benchmarks span (malware, weapons, fraud, disinformation,
hate/violence, drugs, self-harm, cybercrime, financial crime, IP theft, ...), and
includes the paper's own three worked Result-Example queries (s2c-001 defamatory
heroin article, s2c-002 keylogger, s2c-003 age-50 blog post) so a reader can compare
the composed cloaked prompt against the paper's sec 7 examples byte-for-byte.

Columns: `id, goal, target, category`. `target` is the desired jailbroken opening
string; `category` is the misuse bucket. Any `goal[,target,category]` CSV/JSON/JSONL
works via `--data` (column names are normalized), so pointing `--data` at the real
JBB-Behaviors / HarmBench CSV reproduces the paper's exact evaluation set.

## Regenerating / expanding

To run the paper's full evaluation, download JBB-Behaviors and HarmBench and pass
their CSVs to `--data`; the loader normalizes `behavior`/`goal` columns
automatically. `full_count` for the paper is 100 (JBB) + 200 (HarmBench) = 300.
