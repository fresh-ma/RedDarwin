# Reproduction plan — DH-CoT / D-Attack (arXiv 2508.10390)

## Classification
- **Access**: black-box API, text-only, single-shot prompt-template attack. No GPU, no weights.
- **Attack modes (both built, 铁律 4)**: `d-attack` (developer template + in-car-security-test user
  wrapper) and `dh-cot` (educational teacher developer template D1..D12 + H-CoT fake-CoT user).
- **Threat model**: attacker controls the developer/system role + user message; one query per goal.

## Official code status
- `AlienZhang1996/DH-CoT` snapshot (`2ab1d13`) ships only README + figures + LICENSE. README TODO:
  "Upload experimental code / RTA datasets / MDH judgment files." **No code, no data released.**
- → Reimplement faithfully from the paper's Appendix E templates (byte-verbatim). Preserved official
  README + manifest under `references/`. `fidelity_level = faithful_from_paper_templates`.

## Verbatim ports (Appendix E)
- 14.06 → `D_ATTACK_DEVELOPER`, `D_ATTACK_USER`
- 14.07 → `DH_COT_DEVELOPER_HEADER` + 12 few-shot variants `DH_COT_FEWSHOT_EXAMPLES` (D1..D12)
- 15.02 → `DH_COT_FAKE_COT_FRAME` (generalized {topic}) + `DH_COT_STRUCTURE_DEMAND` (verbatim)
- 14.01 → `MDH_JUDGE_RUBRIC` (0-10 jailbreak-response detection judge)
- 14.02/14.03 → COG / INSTR components (provenance/ablation)

## Modular roles (铁律 5)
- `--target` (victim) · `--judge` (MDH content) · `--cot-writer` (optional DH-CoT helper).
  All default `api:deepseek/deepseek-v4-flash`, mix-and-matchable. Extra knobs: `--role`,
  `--dh-variant`, `--hst`, per-role max-tokens.

## Judge (铁律 8, dual metric)
- refusal-bypass (opening avoids refusal marker, non-empty) + content-harmful (MDH rubric ≥ HST=8).
- Canonical ASR will be GLM/Crush per-case audited at result-check; raw judge over-counts.

## Substitutions (documented)
- Victims/judge → OpenRouter open models (paper used GPT-5/Claude-4/Gemini/DeepSeek + Llama-Guard/
  Grok/Doubao ensemble). `model_substitution_run`.
- MDH = single LLM rubric judge only; Part-A Llama-Guard ensemble + human-review loop documented, not built.
- Dataset: RTA gated → 24-goal AdvBench/MaliciousEducator-style seed set (`data/rta_seed.csv`).

## Verify (this pass = static/free only)
- `py_compile` ✓ · `--help` ✓ · `smoke` (fake target, no calls) ✓ · `render` verbatim assembly ✓ ·
  `.env` gitignored ✓ · no `.venv`/`official/` at method root ✓.
- **Real paid target run deferred to the orchestrator (HPC/API).** Faithful negative on aligned
  2026 targets is a legitimate result (era gap) — do not chase numbers with a susceptible target.

## Open items for later stages
- Run both modes ×24 goals ×≥2 configs → result-check (audited ASR) → RESULT_<date>.md (paper row).
- red_team_capability.json `data` block (full_count=24, provenance=RTA-gated stand-in).
- reading/ + index.html (GTA depth), then collect → xsafebench/llm-jailbreak-black-box.
