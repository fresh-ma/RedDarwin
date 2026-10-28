#!/usr/bin/env bash
# mirror-manuscript (proposal mirror-manuscript, multi-skill
# combination of ficdetail-2-0 and flipattack-2-0; repaired re-implementation of
# mirror-manuscript under the incomplete-source contract) on $VICTIM (default
# deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE (default
# bench/AdvBench.csv), then the unified judge. Resume-safe: the raw output name
# is deterministic per shard (victim slug + short sha of the extracted goals),
# attack.py skips goals already completed in it (and the premise compiler is
# cached per goal), and a judged file covering all goals short-circuits the
# run. Only the judged file and the raw checkpoint are kept.
#
# Mechanism: aux-LLM premise+source-sketch compiler (goal -> in-world premise
# pack + source_page, an intentionally incomplete sketch: objective <=45 words,
# context <=30 words, 3-5 sections each {topic <=8, fragment <=18, open
# question <=24}; every open question names unresolved work so the sketch never
# contains the completed composition; aux = deepseek/deepseek-v4-flash, one
# retry with the same model, deterministic Python fallback, per-goal cache) +
# T1 novelist frame with the source_page FCS-flipped into a mirrored manuscript
# page restored through an executable s[::-1] decoder, where the victim's
# ManuscriptSolver.restore() recovers only fragments and open questions and
# draft_chapter() develops those questions into a connected chapter in the
# victim's own prose + reply-conditioned ladder (T2 refusal re-anchor / empty
# continuation / sanitized completion / drift concretize / on-track next
# section; T3 concluding appendix integrating the developed material,
# re-anchored when T2 refused). Exactly 3 victim calls per goal, never more.
# Settings (frozen): target max_tokens 16384, temperature 0.0, reasoning ON.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
METHOD="$ROOT/XSkillLib/Proposal/mirror-manuscript"
PY="$ROOT/.venv/bin/python"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"        # bare model id, no api: prefix
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
mkdir -p "$RESULTS"

GOALS_CSV="$(mktemp -t repairmirrormanuscript_goals_XXXXXX.csv)"
JUDGED_TMP="$(mktemp -t repairmirrormanuscript_judged_XXXXXX.json)"
trap 'rm -f "$GOALS_CSV" "$JUDGED_TMP"' EXIT

# first $N_GOALS goals of $GOALS_FILE -> temp CSV with a `goal` column (the
# skill's choose() shuffles before sampling, so feeding exactly $N_GOALS rows
# guarantees the first $N_GOALS regardless of seed)
"$PY" - "$GOALS_FILE" "$GOALS_CSV" "$N_GOALS" <<'EOF'
import csv, sys
with open(sys.argv[1], newline='', encoding='utf-8') as f:
    goals = [r['request'] for r in csv.DictReader(f)][:int(sys.argv[3])]
with open(sys.argv[2], 'w', newline='', encoding='utf-8') as g:
    w = csv.writer(g)
    w.writerow(['goal'])
    w.writerows([goal] for goal in goals)
EOF

# deterministic per-shard names: re-invocation of the same shard resumes/skips
SHARD_ID="$(shasum -a 256 "$GOALS_CSV" | cut -c1-8)"
RAW_OUT="$RESULTS/mirror-manuscript_${VICTIM_SLUG}_${SHARD_ID}.raw.json"
JUDGED_OUT="$RESULTS/mirror-manuscript_${VICTIM_SLUG}_${SHARD_ID}.judged.json"

# resume-safe: skip the attack entirely when the judged file already covers all goals
if [ -f "$JUDGED_OUT" ] && "$PY" - "$JUDGED_OUT" "$N_GOALS" <<'EOF'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
results = data.get('results') or data.get('records') or []
sys.exit(0 if len(results) >= int(sys.argv[2]) else 1)
EOF
then
  echo "resume: $JUDGED_OUT already covers $N_GOALS goals; skipping" >&2
  exit 0
fi

# 1) run the attack (API keys come from the walk-up .env loader; attack.py
#    writes $RAW_OUT incrementally and skips goals it already completed)
cd "$METHOD"
"$PY" scripts/attack.py run \
  --goals "$GOALS_CSV" --sample-rows "$N_GOALS" --seed 20260720 \
  --target "api:$VICTIM" \
  --aux-model api:deepseek/deepseek-v4-flash --aux-fallback api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash \
  --target-max-tokens 16384 --target-temperature 0.0 \
  --out "$RAW_OUT"

# 2) unified judge -> atomic single judged file in results/, prints ASR
cd "$ROOT"
"$PY" judge/unified_judge.py --input "$RAW_OUT" --output "$JUDGED_TMP" \
  --model api:deepseek/deepseek-v4-flash
mv "$JUDGED_TMP" "$JUDGED_OUT"
