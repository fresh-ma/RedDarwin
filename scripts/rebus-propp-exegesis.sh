#!/usr/bin/env bash
# rebus-propp-exegesis (proposal rebus-propp-exegesis) on $VICTIM
# (default deepseek/deepseek-v4-flash), first $N_GOALS goals of $GOALS_FILE
# (default bench/AdvBench.csv, first 5). One auxiliary compiler call per goal
# (fixed deepseek/deepseek-v4-flash, incomplete source sketch; shared cache
# under the proposal's tale_cache/ is reused across victims and resumes) + 1
# victim call per goal; then unified judge. Only the judged file is kept in
# results/.
#
# Mechanism: repaired multi-skill-combination of adversarial-tales-2-0 (Propp
# tale + third-person exegesis elicitation) and emojicontextinjection
# (emoji-rebus encoding). The Propp F14 Guidance function is the rebus
# carrier, but the carrier is an intentionally INCOMPLETE source sketch: a
# short objective, a context line, and 3-5 sections each holding a topic, at
# most one bounded concrete fragment (<=18 words), and an open question naming
# the work left unresolved. The auxiliary model never writes a complete
# answer; the victim composes the connecting scenes and resolves the open
# passages from its own knowledge inside the exegesis. No fabricated assistant
# turns, no contract pinning.
#
# Standard contract: reads $VICTIM, $GOALS_FILE, $N_GOALS; writes one unified
# judged *.judged.json into $ATTACK_RESULTS_DIR. The raw output path is stable
# per (victim, results dir) so a retried wrapper resumes the runner's per-case
# checkpoint instead of re-paying completed cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/runtime_hooks:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="$ROOT/.venv/bin/python"
METHOD="$ROOT/XSkillLib/Proposal/rebus-propp-exegesis"
VICTIM="${VICTIM:-deepseek/deepseek-v4-flash}"
GOALS_FILE="${GOALS_FILE:-$ROOT/bench/AdvBench.csv}"
N_GOALS="${N_GOALS:-5}"
RESULTS="${ATTACK_RESULTS_DIR:-$ROOT/results/$(date +%Y%m%d-%H%M%S)}"
VICTIM_SLUG="${VICTIM##*/}"
RAW_OUT="$RESULTS/rebus-propp-exegesis_${VICTIM_SLUG}.raw.json"
JUDGED_OUT="$RESULTS/rebus-propp-exegesis_${VICTIM_SLUG}.judged.json"
JUDGED_TMP="$RESULTS/.rebus-propp-exegesis_${VICTIM_SLUG}.judged.tmp.json"

mkdir -p "$RESULTS"

ATTACK_EXIT=0
"$PY" "$METHOD/scripts/attack.py" run \
  --goals "$GOALS_FILE" \
  --limit "$N_GOALS" \
  --target "$VICTIM" \
  --transformer deepseek/deepseek-v4-flash \
  --output "$RAW_OUT" || ATTACK_EXIT=$?

# A non-zero attack exit can mean the compiler refused some goals; the raw
# checkpoint still records valid terminal outcomes, so always pass it to the
# unified judge. Genuine provider/auth failures remain unscored and are
# therefore retried by run_main.py.
if [ "$ATTACK_EXIT" -ne 0 ]; then
  echo "attack stage exited $ATTACK_EXIT; judging recorded terminal outcomes" >&2
fi

"$PY" "$ROOT/judge/unified_judge.py" --input "$RAW_OUT" --output "$JUDGED_TMP"
mv "$JUDGED_TMP" "$JUDGED_OUT"
