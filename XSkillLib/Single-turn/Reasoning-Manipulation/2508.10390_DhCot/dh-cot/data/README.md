# DH-CoT / D-Attack dataset

## `rta_seed.csv` — 24 harmful goals (RTA-style seed set)

**full_count: 24** (counted with the csv module, not `wc -l`).

Columns: `id, goal, category` (+ optional `cot_frame` recognized by the loader for a
verbatim per-goal H-CoT).

### Provenance

The paper evaluates on its **RTA dataset suite** — MDH-cleaned versions of SafeBench,
QuestionSet, JailbreakStudy, BeaverTails, and **MaliciousEducator** (the headline
`RTA-MaliciousEducator`, 50 samples). The official repo
(`AlienZhang1996/DH-CoT`) lists **"Upload RTA datasets"** as a still-open TODO, so
none of the RTA files are public at reproduction time (commit `2ab1d13`).

Because the paper's dataset is **gated (not released)**, this seed set is a small
AdvBench / MaliciousEducator-**style** set of 24 explicitly-harmful goals authored for
this reproduction, spanning the paper's harmful-type taxonomy (Drugs, Weapons, Physical
Harm, Malware, Fraud, Financial Crime, Privacy, Illegal Activity, Hate Speech, Child
Safety). Goals are phrased as "how to …" questions to suit the DH-CoT teacher/educational
framing. It exists to exercise the attack + judge end-to-end; it is **not** the paper's
evaluation set and the ASR it yields is not directly comparable to the paper's headline
numbers.

If the authors release RTA, drop the real CSV in here and point `--data` at it (loader
handles `goal,category,cot_frame` columns); the paper's MaliciousEducator rows carry
pre-built H-CoT prompts that belong in the `cot_frame` column.

### Regenerate / extend

Hand-authored; edit the CSV directly, or generate more AdvBench-style goals and append.
Keep `id` unique and `category` aligned with the harmful-type taxonomy.
