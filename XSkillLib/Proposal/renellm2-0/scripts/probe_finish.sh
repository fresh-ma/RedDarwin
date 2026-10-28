#!/usr/bin/env bash
# Cycle-local helper: resume-until-complete + re-judge empty-judge cells +
# merged-from-shards sync for a list of probe run IDs.
# Judge empty-completion on long outputs is a known infra artifact (repaired
# in judge/unified_judge.py: fallback model fires on empty completions and the
# retry token cap is 8192); this script re-pays only the affected cells.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.."
RUN_IDS="$1"   # space-separated evaluation ids
SPECS="$2"     # parallel list of probe specs, e.g. "--goal-ids 1,2|--sample-size 10 --seed 7"

for round in $(seq 1 25); do
  alldone=1
  i=0
  IFS='|' read -ra SPECLIST <<< "$SPECS"
  for rid in $RUN_IDS; do
    st=$(.venv/bin/python -c "import json;print(json.load(open('runs/forge/$rid/manifest.json'))['status'])" 2>/dev/null || echo missing)
    if [ "$st" != complete ]; then
      alldone=0
      echo "[round $round] resume $rid (status $st)"
      .venv/bin/python forge/evaluate.py probe --proposal renellm2-0 ${SPECLIST[$i]} --resume --run-id "$rid" >/dev/null 2>&1
      # re-judge null-score ok cells at shard level
      RUN_ID="$rid" .venv/bin/python - <<'PYEOF'
import json, glob, os, sys, time
sys.path.insert(0, "judge")
sys.path.insert(0, "XSkillLib/Proposal/renellm2-0/scripts")
import attack
attack.load_env_file(attack.project_env())
import unified_judge as UJ
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1",
                api_key=os.environ.get("OPENROUTER_API_KEY", ""), timeout=300, max_retries=0)
rid = os.environ["RUN_ID"]
def pj(goal, resp):
    for i in range(10):
        try:
            return UJ.judge_one(client, UJ.AUX_PRIMARY_MODEL, goal, resp, 1024)
        except Exception:
            time.sleep(min(30 * (i + 1), 120))
    return None
for f in glob.glob(f"runs/forge/{rid}/results/renellm2-0/*/attempt-*/shards/*/results/*.judged.json"):
    d = json.load(open(f)); dirty = False
    for r in d.get("results", []):
        if r.get("status") == "ok" and r.get("unified_judge", {}).get("score") is None:
            v = pj(r["goal"], r["model_output_text"])
            if v and v.get("score") is not None:
                r["unified_judge"] = v; dirty = True
    if dirty:
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
PYEOF
      # sync merged from shards (prefer ok+scored)
      RUN_ID="$rid" .venv/bin/python - <<'PYEOF'
import json, glob, os
rid = os.environ["RUN_ID"]
for mf in glob.glob(f"runs/forge/{rid}/results/renellm2-0/*/merged/*.judged.json"):
    d = json.load(open(mf)); base = os.path.dirname(os.path.dirname(mf))
    best = {}
    def rank(r):
        s = r.get("unified_judge", {}).get("score")
        return (r.get("status") == "ok", s is not None)
    for sf in sorted(glob.glob(os.path.join(base, "attempt-*", "shards", "*", "results", "*.judged.json"))):
        for r in json.load(open(sf)).get("results", []):
            k = (r["goal"], r["attack_parameters"]["variant"])
            if k not in best or rank(r) > rank(best[k]):
                best[k] = r
    dirty = False
    for i, r in enumerate(d["results"]):
        src = best.get((r["goal"], r["attack_parameters"]["variant"]))
        if src and rank(src) > rank(r):
            d["results"][i] = src; dirty = True
    if dirty:
        json.dump(d, open(mf, "w"), indent=2, ensure_ascii=False)
PYEOF
      .venv/bin/python forge/evaluate.py probe --proposal renellm2-0 ${SPECLIST[$i]} --resume --run-id "$rid" --refresh-only >/dev/null 2>&1
    fi
    i=$((i+1))
  done
  [ "$alldone" = 1 ] && break
  sleep 30
done
for rid in $RUN_IDS; do
  echo "FINAL $rid: $(.venv/bin/python -c "import json;m=json.load(open('runs/forge/$rid/manifest.json'));print(m['status'], m.get('variant_selection_error') or 'freeze-ok')")"
done
