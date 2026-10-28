#!/usr/bin/env bash
set -Eeuo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
python_bin="$repo_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin=$(command -v python3)
fi

exec "$python_bin" - "$repo_root" "$@" <<'PY'
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv.pop(1))
parser = argparse.ArgumentParser(
    prog="scripts/init-redteaming.sh",
    description="Prepare a RedAgent workspace without making model calls.",
    epilog="Example: workspace_001 --bench strongreject_50.csv --goals first-5 --budget 10 --target sol",
)
parser.add_argument("workspace", help="Workspace ID, e.g. workspace_001")
parser.add_argument("--bench", default="strongreject_50.csv", help="CSV under bench/; filename matching is case-insensitive")
parser.add_argument("--goals", default="first-20", help="1-based CSV data rows: first-5, 1-5,8, or all (default: first-20)")
parser.add_argument("--budget", "--budget-per-goal", dest="budget", type=int, default=10, help="Target-call cap per goal (default: 10)")
parser.add_argument("--target", help="OpenRouter model ID")
parser.add_argument("--temperature", type=float, default=0.7)
parser.add_argument("--max-tokens", type=int, default=4096)
args = parser.parse_args()

if not re.fullmatch(r"workspace_[0-9]{3}", args.workspace):
    parser.error("workspace must match workspace_NNN")
if args.budget < 1 or args.max_tokens < 1:
    parser.error("budget and max-tokens must be positive")
if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
    parser.error("temperature must be between 0 and 2")
target = {"sol": "openai/gpt-5.6-sol"}.get(args.target, args.target)
if target is not None and not target:
    parser.error("target cannot be empty")
if target:
    target = target.removeprefix("api:")
    if "/" not in target or not re.fullmatch(r"[A-Za-z0-9_.:/+\-]+", target):
        parser.error("target must be a full OpenRouter model ID or sol")

campaigns = root / "redteaming"
workspace = campaigns / args.workspace
if campaigns.is_symlink() or workspace.is_symlink():
    parser.error("refusing a symlink workspace")
if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
    parser.error("refusing to initialize a non-empty workspace; resume it instead")

name = args.bench.removeprefix("bench/")
if "/" in name or "\\" in name or name in {"", ".", ".."}:
    parser.error("bench must name a CSV directly under bench/")
if not name.lower().endswith(".csv"):
    name += ".csv"
matches = [p for p in (root / "bench").iterdir() if p.is_file() and p.name.casefold() == name.casefold()]
if len(matches) != 1:
    parser.error("benchmark CSV not found or ambiguous: " + args.bench)
source = matches[0]
if source.resolve().parent != (root / "bench").resolve():
    parser.error("benchmark must remain inside bench/")
with source.open(encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    headers = reader.fieldnames or []
    rows = list(reader)
column = next((k for k in ["query", "request", "goal", "prompt", "instruction", "behavior"] if k in headers), None)
if column is None:
    parser.error("CSV needs a query, request, goal, prompt, instruction, or behavior column")

selection = args.goals.strip().lower()
if selection == "all":
    selected = list(range(1, len(rows) + 1))
elif re.fullmatch(r"first-[1-9][0-9]*", selection):
    count = int(selection[6:])
    if count > len(rows):
        parser.error("selected rows exceed the CSV's %d data rows" % len(rows))
    selected = list(range(1, count + 1))
else:
    selected = []
    for part in selection.split(","):
        part = part.strip()
        if not re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?", part):
            parser.error("goals must be first-N, all, or 1-based rows such as 1-5,8")
        ends = [int(x) for x in part.split("-")]
        if ends[-1] > len(rows) or ends[-1] < ends[0]:
            parser.error("goal ranges must be ascending and within the CSV")
        selected.extend(range(ends[0], ends[-1] + 1))
if not selected or len(selected) > 999 or any(n > len(rows) for n in selected):
    parser.error("selected rows are out of bounds (CSV has %d data rows)" % len(rows))
if len(set(selected)) != len(selected):
    parser.error("goal selection contains duplicate rows")

goals = []
for order, row_number in enumerate(selected, 1):
    row = rows[row_number - 1]
    text = row.get(column)
    if not isinstance(text, str) or not text.strip():
        parser.error("selected CSV row %d has an empty goal" % row_number)
    entry = {"goal_id": "goal_%03d" % order, "order": order, "goal": text}
    for key, value in row.items():
        if key and key not in {column, "goal_id", "order", "goal", "source_row"} and value:
            if (key.endswith("index") or key.endswith("seed") or key in {"id", "advbench_id"}) and re.fullmatch(r"-?[0-9]+", value):
                value = int(value)
            entry[key] = value
    entry["source_row"] = row_number
    goals.append(entry)

templates = root / "agent_protocols/RedAgent/templates"
required = ["RUN.json", "RECORDING.md", "schemas/trail.schema.json", "goal_001/summary.json"]
if any(not (templates / name).is_file() for name in required):
    parser.error("campaign templates are incomplete")
run = json.loads((templates / "RUN.json").read_text())
goal_summary = json.loads((templates / "goal_001/summary.json").read_text())
sys.path.insert(0, str(root))
from openrouter_routing import provider_route_for_model

source_name = str(source.relative_to(root))
snapshot = {"source": source_name, "selection": selection, "source_rows": selected,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "goals": goals}
snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
run.update(campaign=args.workspace, created=datetime.now(timezone.utc).isoformat(),
           goals_file=source_name, goals_selection=selection, goal_count=len(goals),
           goals_sha256=hashlib.sha256(snapshot_text.encode()).hexdigest(), locked=bool(target))
run["target"].update(model=target, provider=(provider_route_for_model(target) or {}) if target else None,
                     temperature=args.temperature, max_tokens=args.max_tokens)
run["budget"].update(victim_calls_per_goal=args.budget, victim_calls_per_target=len(goals) * args.budget)

campaigns.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix=".init-", dir=campaigns) as temporary:
    staging = Path(temporary) / args.workspace
    staging.mkdir()
    for item in templates.iterdir():
        if item.name in {"RUN.json", "goals.json", "SUMMARY.md"} or item.name.startswith("goal_"):
            continue
        if item.is_dir():
            shutil.copytree(item, staging / item.name)
        else:
            shutil.copy2(item, staging / item.name)
    for name in ["code", "logs", "tmp"]:
        (staging / name).mkdir(exist_ok=True)
    (staging / "RUN.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    (staging / "goals.json").write_text(snapshot_text)
    for goal in goals:
        directory = staging / goal["goal_id"]
        directory.mkdir()
        (directory / "goal.json").write_text(json.dumps(goal, ensure_ascii=False, indent=2) + "\n")
        summary = dict(goal_summary, goal_id=goal["goal_id"])
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (staging / "SUMMARY.md").write_text(
        "# Campaign Summary\n\nStatus: not started.\n\n"
        "- Target: %s\n- Benchmark: %s (%s)\n- Goals completed: 0/%d\n"
        "- Victim calls: 0/%d\n- Judgments: none\n"
        "- ASR@1 / ASR@5 / ASR@10: not measured\n"
        % (target or "not selected", source_name, selection, len(goals), len(goals) * args.budget))
    if workspace.exists():
        workspace.rmdir()  # Refuses a directory populated after the earlier check.
    staging.rename(workspace)

print("Initialized: " + str(workspace))
print("Benchmark: %s; rows: %s; goals: %d" % (source_name, selection, len(goals)))
print("Budget: %d per goal, %d total" % (args.budget, len(goals) * args.budget))
print("Target: " + (target or "supply it when starting the agent"))
PY
