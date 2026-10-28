# Reproduction plan — S2C (arXiv 2603.16192)

## Decision summary (plan-first gate)

| Choice | Decision | Rationale |
|---|---|---|
| Repro depth | Full pipeline, faithful_from_paper | No official code; all 5 stages reimplemented from paper text/tables/examples |
| Access | Black-box, single-shot prompt transform | Paper accesses targets via API; attack is one composed prompt per query |
| Reframer | `api:deepseek/deepseek-v4-flash` (paper: Gemma-2-9B-it) | Open-model substitution per project default; role preserved, swappable flag |
| Extractor | `api:deepseek/deepseek-v4-flash` (paper: GPT-4.1-mini + spaCy) | LLM sensitive-word extraction path; spaCy NP/VP is an alternative fragmentation route not required for the main framework |
| Target | `api:deepseek/deepseek-v4-flash` | Project default black-box victim |
| Judge | Dual-metric LLM judge (paper: HarmBench Llama-2-13B) | Released-classifier substitution; content_harmful + refusal_bypass |
| Data | Generated 25-goal seed (paper: JBB-Behaviors 100 + HarmBench 200, not redistributed) | `--data` accepts the real benchmark CSVs to reproduce the full set |
| Cost | Sample run only (≥20 cases); no GPU | Black-box API, single call per goal |

## Method (faithful anchors)

- `F: Q -> P` pipeline (sec 3.2–3.3): Contextual Reframing → Key Term Extraction →
  Content Fragmentation → Clue-guided Camouflage → Cloaked Prompt Composition.
- Reframing prompt: sec 6.2 (verbatim, `prompts.REFRAMING_PROMPT`).
- Extraction prompt: sec 6.3 (verbatim, `prompts.EXTRACTION_PROMPT`).
- Obfuscation pool Ω: Table `tab:obfuscation_method` (`obfuscate.py`); 7 default
  cascades from sec 4.1.5.
- Composition wrapper + decode HINTs: sec 6.4 + sec 7 Result Example 1 (byte-matched;
  Caesar `defamatory → efgbnbupsz` reproduces exactly).
- Metrics: ASR (→ content_harmful), RSR via `--measure-rsr` (sec 6.4).

## Verification done (free / static, no paid runs)

- `python -m py_compile scripts/*.py` — OK.
- `attack.py --help` / `run --help` — all subcommands + modular role flags present.
- `smoke` (fake roles, no API) — pipeline shape + result schema OK.
- `render` offline — composed cloaked prompt matches sec 7 example byte-for-byte;
  cascades (reversal+a1z26, reversal+word_play, reversal+base64) compose correctly;
  raw `behavior`-only JSON dataset flexibility OK.

## Not yet done (needs Oscar / API budget)

- Real `--sample 20` run against a live target + LLM judge (paid; deferred per task).
- Point `--data` at real JBB-Behaviors / HarmBench for the paper's full 300-query eval.
- `red_team_capability.json` + `index.html` (collect stage).
