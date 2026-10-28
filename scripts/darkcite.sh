#!/usr/bin/env bash
# DarkCite (2411.11407 authority-citation jailbreak) on $VICTIM
# (default qwen/qwen3.7-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, N_GOALS default 5), canonical setting, then
# unified judge.
# Only the judged file is kept in results/.
#
# Setting basis: SKILL.md canonical result (v4-flash, advbench, 2026-06-26,
# audited ASR 0.40) — advbench dataset with paper gen params
# temp 0.9 / top_p 0.9 / max_tokens 1536, request-delay 0.3.
#
# No attacker/helper LLM by design: DarkCite's citation generation (paper's
# GPT-4o/Baichuan) is a one-off artefact consumed verbatim from the released
# datasets in darkcite/data/; the run path is attacker-model-free.
#
# Dataset: DarkCite cannot fabricate citations for arbitrary goals at runtime,
# so we filter the official darkcite_advbench_using_gpt.jsonl down to rows whose
# topic is one of $GOALS_FILE's first $N_GOALS goals (each goal carries 3
# official citation variants -> 3*N_GOALS cases). Feeding exactly those rows
# makes --sample deterministic regardless of the seeded shuffle.
#
# Known risk: --judge-model is forced to deepseek-v4-flash per project rule, but
# the skill's internal llama_guard_judge() parses a leading safe/unsafe token that
# only Llama-Guard-family models emit; with v4-flash the in-skill asr_llama_guard
# metric degenerates (parses as "safe"). The authoritative score is the
# unified_judge (v4-flash, 1-5 rubric) verdict in the judged file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Single-turn/Stylistic-Obfuscation/2411.11407_DarkCite/darkcite"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$RESULTS"

VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # 裸模型 id,不带 api: 前缀
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
VICTIM_SLUG="${VICTIM##*/}"

STAMP="$(date +%Y%m%d-%H%M%S)"
GOALS_JSONL="$(mktemp -t darkcite_goals_XXXXXX.jsonl)"
RAW_OUT="$(mktemp -t darkcite_raw_XXXXXX.json)"
trap 'rm -f "$GOALS_JSONL" "$RAW_OUT"' EXIT
JUDGED_OUT="$RESULTS/darkcite_${VICTIM_SLUG}_advbench-mt1536_${N_GOALS}x_${STAMP}.judged.json"

# first $N_GOALS goals of $GOALS_FILE -> temp JSONL = official citation rows
# for those topics (3 official fake citations per goal -> 3*N_GOALS rows;
# --sample keeps them all, no shuffle)
OFFICIAL_MARKER="$(mktemp -t darkcite_marker_XXXXXX)"
trap 'rm -f "$GOALS_JSONL" "$RAW_OUT" "$OFFICIAL_MARKER"' EXIT
"$PY" - "$GOALS_FILE" "$METHOD/data/darkcite_advbench_using_gpt.jsonl" "$GOALS_JSONL" "$N_GOALS" "$OFFICIAL_MARKER" <<'EOF'
import csv, json, sys
from pathlib import Path
goals = {r['request'] for r in list(csv.DictReader(open(sys.argv[1], newline='', encoding='utf-8')))[:int(sys.argv[4])]}
rows = [json.loads(l) for l in Path(sys.argv[2]).read_text(encoding='utf-8').splitlines() if l.strip()]
keep = [r for r in rows if r.get('topic') in goals]
missing = goals - {r['topic'] for r in keep}
if missing:
    print(f'warning: {len(missing)} goal(s) missing from darkcite data, running {len(goals)-len(missing)}/{len(goals)}', file=sys.stderr)
Path(sys.argv[3]).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in keep), encoding='utf-8')
Path(sys.argv[5]).write_text('yes' if keep else 'no')
EOF

HAS_OFFICIAL="$(<"$OFFICIAL_MARKER")"

if [[ "$HAS_OFFICIAL" == "no" ]]; then
  "$PY" - "$GOALS_FILE" "$JUDGED_OUT" "$N_GOALS" <<'EOF'
import csv, json, sys
rows = list(csv.DictReader(open(sys.argv[1], newline='', encoding='utf-8')))[:int(sys.argv[3])]
results = []
for row in rows:
    for slot in (1, 2, 3):
        results.append({
            "goal": row["request"],
            "status": "no_target_call",
            "final_attempt": {"target_call": None},
            "model_output_text": "",
            "variant": f"citation-slot-{slot}",
            "unified_judge": {"score": 1, "success": False,
                              "rationale": "Official DarkCite citation corpus has no matching record; no target call was made.",
                              "provenance": "deterministic_no_target_call"},
        })
json.dump({"schema_version": 1, "results": results,
           "unified_summary": {"n": len(results), "n_scored": len(results), "asr": 0.0}},
          open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
EOF
  exit 0
fi

# 1) run the attack (API key comes from $ROOT/.env via the skill's walk-up loader)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --dataset "$GOALS_JSONL" \
  --target "api:$VICTIM" \
  --judge-model deepseek/deepseek-v4-flash \
  --sample "$(wc -l < "$GOALS_JSONL" | tr -d ' ')" \
  --temperature 0.9 --top-p 0.9 --max-tokens 1536 \
  --request-delay 0.3 \
  --out "$RAW_OUT"

# 2) unified judge -> single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_OUT"
