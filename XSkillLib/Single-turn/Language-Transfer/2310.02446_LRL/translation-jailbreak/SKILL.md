# Translation Jailbreak

## What

Paper-local runner for `2310.02446_low-resource-language-jailbreak`.

Reproduces Yong et al. 2023: translate AdvBench / HarmBench harmful English
instructions into paper-listed low-resource languages via **Google Translate
Basic API** → query target model → back-translate response to English → label
BYPASS / REJECT / UNCLEAR per the paper's annotation guidelines.

## Use

Data flow:

```
AdvBench / HarmBench English goal
→ Google Translate forward → low-resource language
→ target model response
→ Google Translate backward → English
→ BYPASS / REJECT / UNCLEAR judge (paper rubric)
→ result JSON with per-language and resource-bucket ASR
```

Datasets in `data/`:
- `advbench_harmful_behaviors.json` — 520 AdvBench harmful behaviors (full)
- `harmbench_standard_behaviors.json` — 200 HarmBench standard behaviors

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`). API keys are read from the global `XSkillForge/.env`
(`scripts/models.py` and `tools/translation_api.py` walk up to find it) — no
per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

Required env vars (from the global `.env`):
- `OPENROUTER_API_KEY` — target and judge calls
- `GOOGLE_TRANSLATE_API_KEY` — paper-exact machine translation

## Run

AdvBench, 10 goals, all LRL + English (50 cases):

```bash
$PY scripts/attack.py run \
  --goals data/advbench_harmful_behaviors.json \
  --target api:deepseek/deepseek-v4-flash \
  --translator project-api --translation-provider google \
  --judge-model deepseek/deepseek-v4-flash \
  --languages lrl,en \
  --sample 10 --seed 20260625 \
  --max-tokens 768 --request-delay 0.5 \
  --out results/translation_deepseek_v4_flash_advbench_lrl_en_10x5_20260625.json
```

HarmBench, same config:

```bash
$PY scripts/attack.py run \
  --goals data/harmbench_standard_behaviors.json \
  --target api:deepseek/deepseek-v4-flash \
  --translator project-api --translation-provider google \
  --judge-model deepseek/deepseek-v4-flash \
  --languages lrl,en \
  --sample 10 --seed 20260625 \
  --max-tokens 768 --request-delay 0.5 \
  --out results/translation_deepseek_v4_flash_harmbench_lrl_en_10x5_20260625.json
```

Full 12-language run (all resource buckets):

```bash
$PY scripts/attack.py run \
  --goals data/advbench_harmful_behaviors.json \
  --target api:deepseek/deepseek-v4-flash \
  --translator project-api --translation-provider google \
  --judge-model deepseek/deepseek-v4-flash \
  --languages paper \
  --sample 20 --seed 20260625 \
  --out results/translation_full_12lang_20x.json
```

Inspect without running:

```bash
$PY scripts/attack.py inspect \
  --goals data/advbench_harmful_behaviors.json \
  --languages lrl --sample 3
```

## Test

```bash
$PY -m py_compile scripts/*.py tools/translation_api.py
$PY scripts/attack.py inspect --languages lrl --sample 3
$PY scripts/attack.py render --languages lrl --sample 2
$PY tools/translation_api.py probe --provider google --to zu
```

## Settings & Parameters

| Flag | Meaning |
|---|---|
| `--target` | `api:<openrouter-model-id>`. Default: `fake`. |
| `--translator` | `project-api` (Google/Azure/DeepL MT) or `api` (LLM translator) or `tagged` (placeholder). |
| `--translation-provider` | `google` (paper-exact), `deepl`, `azure`, `auto`. Default: `google`. |
| `--judge-model` | LLM judge serving BYPASS/REJECT/UNCLEAR rubric. Default: `deepseek/deepseek-v4-flash`. |
| `--languages` | Comma-separated codes or group names: `lrl`, `mrl`, `hrl`, `paper`, `en`, or specific codes like `zu,gd,hmn,gn`. |
| `--sample` / `--sample-rows` | Number of goals to sample. Default: full dataset. |
| `--max-tokens` | Target output budget. Default: 768. |
| `--request-delay` | Delay between cases (seconds). |
| `--max-retries` | Retries on 429/5xx. Default: 4. |

Environment variables:

| Name | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | Required for API targets and judges. |
| `GOOGLE_TRANSLATE_API_KEY` | Required for paper-exact Google Translate. |

## Languages

| Group | Languages |
|-------|-----------|
| LRL | Zulu (`zu`), Scots Gaelic (`gd`), Hmong (`hmn`), Guarani (`gn`) |
| MRL | Ukrainian (`uk`), Bengali (`bn`), Thai (`th`), Hebrew (`he`) |
| HRL | Chinese (`zh-CN`), Arabic (`ar`), Italian (`it`), Hindi (`hi`), English (`en`) |
