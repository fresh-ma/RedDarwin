#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .common import (
        DEFAULT_VICTIMS,
        MEMORY_DIR,
        MEMORY_INDEX,
        ROOT,
        atomic_write_json,
        extract_goal,
        find_records,
        load_benchmarks,
        normalize_goal,
        parse_advbench_ids,
        repo_relative,
        resolve_repo_path,
        sha256,
        slug,
        utc_now,
    )
    from .evaluate import inspect_result
    from .memory_store import (
        consolidate_cycle,
        evaluation_entry,
        rebuild_index,
        register_evaluation,
    )
except ImportError:  # Support the documented `python forge/memory.py` form.
    from common import (
        DEFAULT_VICTIMS,
        MEMORY_DIR,
        MEMORY_INDEX,
        ROOT,
        atomic_write_json,
        extract_goal,
        find_records,
        load_benchmarks,
        normalize_goal,
        parse_advbench_ids,
        repo_relative,
        resolve_repo_path,
        sha256,
        slug,
        utc_now,
    )
    from evaluate import inspect_result
    from memory_store import consolidate_cycle, evaluation_entry, rebuild_index, register_evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and query multi-level XSkillForge memory. The JSON index remains directly readable."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("rebuild", help="Rebuild memory/index.json from the locked standard archive and compatible new evaluations")

    goal = subparsers.add_parser("goal", help="Compare full evidence pointers for one AdvBench goal")
    goal.add_argument("sample_id", help="Integer AdvBench ID, advbench-XXXX, subset-XXX, or s-XXX")
    goal.add_argument("--skill", action="append", default=[])
    goal.add_argument("--victim", action="append", default=[])
    goal.add_argument("--evaluation", action="append", default=[])
    goal.add_argument("--outcome", action="append", choices=("success", "failure", "unscored"), default=[])
    goal.add_argument("--formal-only", action="store_true")
    goal.add_argument("--raw", action="store_true", help="Load and include the complete source JSON record")
    goal.add_argument("--verify", action="store_true", help="Verify source SHA-256 before loading evidence")
    goal.add_argument("--json", action="store_true", dest="as_json")

    records = subparsers.add_parser(
        "records",
        help="Load complete historical records for one or more exact AdvBench IDs",
    )
    records.add_argument("--goal-ids", action="append", required=True, help="Comma-separated zero-based AdvBench IDs")
    records.add_argument("--skill", action="append", default=[])
    records.add_argument("--victim", action="append", default=[])
    records.add_argument("--evaluation", action="append", default=[])
    records.add_argument("--outcome", action="append", choices=("success", "failure", "unscored"), default=[])
    records.add_argument("--formal-only", action="store_true")
    records.add_argument("--raw", action="store_true", help="Include each complete source JSON record")
    records.add_argument("--verify", action="store_true", help="Verify source SHA-256 before loading evidence")
    records.add_argument(
        "--all",
        action="store_true",
        help="Return every matching trajectory instead of one preferred record per skill/victim/goal",
    )
    records.add_argument("--output", help="Also write the structured JSON result to this path")

    skill = subparsers.add_parser("skill", help="Show the evaluation trajectory and published baseline for a skill")
    skill.add_argument("skill_id")
    skill.add_argument("--json", action="store_true", dest="as_json")

    evaluation = subparsers.add_parser("evaluation", help="Show one registered evaluation")
    evaluation.add_argument("evaluation_id")
    evaluation.add_argument("--json", action="store_true", dest="as_json")

    listing = subparsers.add_parser("list", help="List registered evaluations")
    listing.add_argument("--skill")
    listing.add_argument("--cycle")
    listing.add_argument("--formal-only", action="store_true")
    listing.add_argument("--json", action="store_true", dest="as_json")

    consolidate = subparsers.add_parser("consolidate", help="Create/update an L2 cycle summary from all run logs")
    consolidate.add_argument("--cycle", required=True)

    import_run = subparsers.add_parser("import-run", help="Register an existing run without moving or editing evidence")
    import_run.add_argument("--run-dir", required=True)
    import_run.add_argument("--evaluation-id", required=True)
    import_run.add_argument("--mode", required=True, choices=("partial", "full"))
    import_run.add_argument("--cycle", required=True)
    import_run.add_argument("--skill", action="append", default=[], help="Only import these inferred skill IDs")
    import_run.add_argument("--formal", action="store_true")
    import_run.add_argument(
        "--proposal-type",
        choices=("single-skill-evolution", "multi-skill-combination", "new-skill-creation"),
    )
    import_run.add_argument("--notes", default="")
    return parser.parse_args()


def load_index() -> dict[str, Any]:
    if not MEMORY_INDEX.exists():
        raise SystemExit(f"memory index missing; run: {sys.executable} forge/memory.py rebuild")
    return json.loads(MEMORY_INDEX.read_text(encoding="utf-8"))


def resolve_skill_id(skill_ref: str) -> str:
    path = ROOT / "LEADERBOARD.json"
    if not path.is_file():
        return skill_ref
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("leaderboard", [])
    # Stable IDs take precedence over display/attack aliases.  Base and 2.0
    # standard rows intentionally share the canonical attack label.
    for row in rows:
        stable_id = row.get("skill_id", row.get("attack"))
        if skill_ref == stable_id:
            return str(stable_id)
    aliases = [
        str(row.get("skill_id", row.get("attack")))
        for row in rows
        if skill_ref in (row.get("attack"), row.get("display_name"))
    ]
    if len(set(aliases)) == 1:
        return aliases[0]
    return skill_ref


def resolve_sample(index: dict[str, Any], raw: str) -> dict[str, Any]:
    advbench_id: int | None = None
    subset_index: int | None = None
    if raw.isdigit():
        advbench_id = int(raw)
    elif match := re.fullmatch(r"advbench-(\d+)", raw.lower()):
        advbench_id = int(match.group(1))
    elif match := re.fullmatch(r"(?:subset|s)-(\d+)", raw.lower()):
        subset_index = int(match.group(1))
    else:
        raise SystemExit("sample_id must be an integer, advbench-XXXX, subset-XXX, or s-XXX")
    for sample in index["samples"]:
        if advbench_id is not None and sample["advbench_id"] == advbench_id:
            return sample
        if subset_index is not None and sample.get("subset_index") == subset_index:
            return sample
    raise SystemExit(f"sample not present: {raw}")


def load_raw_record(observation: dict[str, Any], verify: bool) -> dict[str, Any]:
    source = resolve_repo_path(observation["source_file"])
    if not source.exists():
        return {"error": f"source file does not exist: {repo_relative(source)}"}
    if verify and observation.get("source_sha256"):
        actual = sha256(source)
        if actual != observation["source_sha256"]:
            return {"error": "source SHA-256 mismatch", "actual_sha256": actual}
    records = find_records(json.loads(source.read_text(encoding="utf-8")))
    record_index = observation.get("record_index")
    if not isinstance(record_index, int) or not 0 <= record_index < len(records):
        return {"error": "record pointer is outside the source record list"}
    return records[record_index]


def goal_command(index: dict[str, Any], args: argparse.Namespace) -> int:
    sample = resolve_sample(index, args.sample_id)
    observations = []
    for row in index["observations"]:
        if row["advbench_id"] != sample["advbench_id"]:
            continue
        if args.skill and row.get("skill") not in args.skill:
            continue
        if args.victim and row.get("victim") not in args.victim:
            continue
        if args.evaluation and row.get("evaluation_id") not in args.evaluation:
            continue
        if args.outcome and row.get("outcome") not in args.outcome:
            continue
        if args.formal_only and not row.get("formal"):
            continue
        item = dict(row)
        if args.raw:
            item["raw_record"] = load_raw_record(item, args.verify)
        observations.append(item)
    result = {"sample": sample, "count": len(observations), "observations": observations}
    if args.as_json or args.raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(
        f"{sample['advbench_key']} subset={sample.get('subset_index')} "
        f"observations={len(observations)}\n"
    )
    print("evaluation\tskill\tvictim\tvariant\toutcome\tscore\tsource")
    for row in observations:
        print(
            "\t".join(
                str(value) if value is not None else "NA"
                for value in (
                    row.get("evaluation_id"),
                    row.get("skill"),
                    row.get("victim"),
                    row.get("variant"),
                    row.get("outcome"),
                    row.get("score"),
                    f"{row.get('source_file')}#{row.get('record_index')}",
                )
            )
        )
    return 0


def observation_matches(row: dict[str, Any], args: argparse.Namespace) -> bool:
    return not (
        (args.skill and row.get("skill") not in args.skill)
        or (args.victim and row.get("victim") not in args.victim)
        or (args.evaluation and row.get("evaluation_id") not in args.evaluation)
        or (args.outcome and row.get("outcome") not in args.outcome)
        or (args.formal_only and not row.get("formal"))
    )


def records_command(index: dict[str, Any], args: argparse.Namespace) -> int:
    try:
        requested_ids = parse_advbench_ids(args.goal_ids)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    samples_by_id = {sample["advbench_id"]: sample for sample in index["samples"]}
    missing = [sample_id for sample_id in requested_ids if sample_id not in samples_by_id]
    if missing:
        raise SystemExit(f"AdvBench IDs not present in memory index: {missing}")

    observations_by_id: dict[int, list[dict[str, Any]]] = {sample_id: [] for sample_id in requested_ids}
    for row in index["observations"]:
        sample_id = row.get("advbench_id")
        if sample_id not in observations_by_id or not observation_matches(row, args):
            continue
        observations_by_id[sample_id].append(dict(row))

    evaluation_order = {
        entry.get("evaluation_id"): position
        for position, entry in enumerate(index.get("evaluations", []))
    }

    def preference(row: dict[str, Any]) -> tuple[Any, ...]:
        usable = row.get("status") == "ok" and row.get("score") is not None
        return (
            row.get("source_tier") not in ("published", "standard-published", "published-proposal"),
            not usable,
            row.get("mode") not in ("full", "final"),
            not bool(row.get("formal")),
            not bool(row.get("selected_global_variant", True)),
            -evaluation_order.get(row.get("evaluation_id"), -1),
            str(row.get("evaluation_id") or ""),
        )

    selected_by_id: dict[int, list[dict[str, Any]]] = {}
    alternatives_by_id: dict[int, list[dict[str, Any]]] = {}
    pointer_fields = (
        "evaluation_id",
        "mode",
        "formal",
        "skill",
        "victim",
        "variant",
        "outcome",
        "score",
        "status",
        "source_tier",
        "source_file",
        "source_sha256",
        "record_index",
    )
    for sample_id, observations in observations_by_id.items():
        observations.sort(key=lambda row: (str(row.get("skill") or ""), str(row.get("victim") or ""), preference(row)))
        if args.all:
            selected = observations
            alternatives: list[dict[str, Any]] = []
        else:
            grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
            for row in observations:
                grouped.setdefault((row.get("skill"), row.get("victim")), []).append(row)
            selected = [min(group, key=preference) for group in grouped.values()]
            selected_ids = {id(row) for row in selected}
            alternatives = [
                {key: row.get(key) for key in pointer_fields if key in row}
                for row in observations
                if id(row) not in selected_ids
            ]
        for item in selected:
            item["preferred"] = not args.all
            if args.raw:
                raw_record = load_raw_record(item, args.verify)
                if "error" in raw_record:
                    raise SystemExit(
                        f"cannot load {item.get('source_file')}#{item.get('record_index')}: "
                        f"{raw_record['error']}"
                    )
                item["raw_record"] = raw_record
        selected_by_id[sample_id] = selected
        alternatives_by_id[sample_id] = alternatives
    goals = [
        {
            "sample": samples_by_id[sample_id],
            "count": len(selected_by_id[sample_id]),
            "available_count": len(observations_by_id[sample_id]),
            "observations": selected_by_id[sample_id],
            "alternative_pointers": alternatives_by_id[sample_id],
        }
        for sample_id in requested_ids
    ]
    result = {
        "query": {
            "goal_ids": requested_ids,
            "skills": args.skill,
            "victims": args.victim,
            "evaluations": args.evaluation,
            "outcomes": args.outcome,
            "formal_only": args.formal_only,
            "raw": args.raw,
            "verify": args.verify,
            "all": args.all,
            "network_calls": 0,
            "selection_policy": (
                "all matching trajectories"
                if args.all
                else "one preferred usable published/final/formal record per skill/victim/goal; use --all for every trajectory"
            ),
        },
        "goal_count": len(goals),
        "observation_count": sum(goal["count"] for goal in goals),
        "available_observation_count": sum(goal["available_count"] for goal in goals),
        "goals": goals,
    }
    if args.output:
        output = resolve_repo_path(args.output)
        atomic_write_json(output, result)
        print(
            json.dumps(
                {
                    "output": repo_relative(output),
                    "goal_count": result["goal_count"],
                    "observation_count": result["observation_count"],
                    "available_observation_count": result["available_observation_count"],
                    "network_calls": 0,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def published_baseline(skill_id: str) -> dict[str, Any] | None:
    path = ROOT / "LEADERBOARD.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("leaderboard", [])
    exact = next((row for row in rows if row.get("skill_id", row.get("attack")) == skill_id), None)
    if exact is not None:
        return exact
    aliases = [row for row in rows if row.get("attack") == skill_id or row.get("display_name") == skill_id]
    return aliases[0] if len(aliases) == 1 else None


def recommended_baseline_evaluation(index: dict[str, Any], skill_id: str) -> str | None:
    if published_baseline(skill_id) is not None:
        return "published-leaderboard"
    candidates = []
    for position, entry in enumerate(index.get("evaluations", [])):
        complete_cell = any(
            cell.get("skill") == skill_id and cell.get("status") == "complete"
            for cell in entry.get("cells", [])
        )
        if not complete_cell:
            continue
        candidates.append(
            (
                entry.get("mode") in ("full", "final"),
                bool(entry.get("formal")),
                position,
                entry.get("evaluation_id"),
            )
        )
    return max(candidates)[-1] if candidates else None


def skill_command(index: dict[str, Any], args: argparse.Namespace) -> int:
    evaluations = []
    for entry in index["evaluations"]:
        cells = [cell for cell in entry.get("cells", []) if cell.get("skill") == args.skill_id]
        if cells:
            evaluations.append(
                {
                    "evaluation_id": entry.get("evaluation_id"),
                    "created_at": entry.get("created_at"),
                    "mode": entry.get("mode"),
                    "formal": entry.get("formal"),
                    "cycle": entry.get("cycle"),
                    "status": entry.get("status"),
                    "cells": cells,
                    "manifest": entry.get("manifest"),
                }
            )
    result = {
        "skill": args.skill_id,
        "recommended_baseline_evaluation_id": recommended_baseline_evaluation(index, args.skill_id),
        "published_baseline": published_baseline(args.skill_id),
        "evaluations": evaluations,
    }
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    baseline = result["published_baseline"]
    print(f"skill: {args.skill_id}")
    print(f"published mean ASR: {baseline.get('mean_asr') if baseline else 'NA'}")
    print(f"recommended baseline evaluation: {result['recommended_baseline_evaluation_id'] or 'NA'}")
    print("evaluation\tmode\tformal\tcycle\tvictim\tstatus\tvariant\tasr")
    for entry in evaluations:
        for cell in entry["cells"]:
            selected = cell.get("selected", {})
            print(
                "\t".join(
                    str(value) if value is not None else "NA"
                    for value in (
                        entry["evaluation_id"],
                        entry["mode"],
                        entry["formal"],
                        entry["cycle"],
                        cell.get("victim"),
                        cell.get("status"),
                        selected.get("variant"),
                        selected.get("asr"),
                    )
                )
            )
    return 0


def evaluation_command(index: dict[str, Any], args: argparse.Namespace) -> int:
    entry = next(
        (row for row in index["evaluations"] if row.get("evaluation_id") == args.evaluation_id),
        None,
    )
    if entry is None:
        raise SystemExit(f"evaluation not found: {args.evaluation_id}")
    if args.as_json:
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def list_command(index: dict[str, Any], args: argparse.Namespace) -> int:
    entries = []
    for row in index["evaluations"]:
        if args.skill and args.skill not in row.get("skills", []):
            continue
        if args.cycle and args.cycle != row.get("cycle"):
            continue
        if args.formal_only and not row.get("formal"):
            continue
        entries.append(row)
    if args.as_json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    print("evaluation\tmode\tformal\tcycle\tstatus\tskills")
    for row in entries:
        print(
            "\t".join(
                str(value)
                for value in (
                    row.get("evaluation_id"),
                    row.get("mode"),
                    row.get("formal"),
                    row.get("cycle"),
                    row.get("status"),
                    ",".join(row.get("skills", [])),
                )
            )
        )
    return 0


def infer_result_identity(path: Path) -> tuple[str, str] | None:
    stem = path.name[: -len(".judged.json")] if path.name.endswith(".judged.json") else path.stem
    for victim in DEFAULT_VICTIMS:
        marker = f"_{victim.split('/')[-1]}_"
        if marker in stem:
            return stem.split(marker, 1)[0], victim
    return None


def import_run_command(args: argparse.Namespace) -> int:
    run_dir = resolve_repo_path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")
    evaluation_id = slug(args.evaluation_id)
    cycle = slug(args.cycle)
    samples, _ = load_benchmarks()
    goal_lookup = {normalize_goal(sample["goal"]): sample for sample in samples}
    cells = []
    goal_ids: set[int] = set()
    selected_skills = set(args.skill)
    for result_path in sorted(run_dir.rglob("*.judged.json")):
        identity = infer_result_identity(result_path)
        if identity is None:
            continue
        skill, victim = identity
        if selected_skills and skill not in selected_skills:
            continue
        records = find_records(json.loads(result_path.read_text(encoding="utf-8")))
        expected_goals = set()
        for record in records:
            normalized = normalize_goal(extract_goal(record))
            sample = goal_lookup.get(normalized)
            if sample is not None:
                expected_goals.add(normalized)
                goal_ids.add(sample["advbench_id"])
        cell = inspect_result(result_path, skill, victim, expected_goals, 1.0)
        victim_slug = victim.split("/")[-1]
        log_candidates = sorted((run_dir / "logs").glob(f"{skill}_{victim_slug}*.log"))
        cell["log_file"] = repo_relative(log_candidates[0]) if log_candidates else None
        cell["imported"] = True
        cells.append(cell)
    if not cells:
        raise SystemExit("no judged result files with recognized victim names were found")
    imported_skills = sorted({cell["skill"] for cell in cells})
    missing = selected_skills.difference(imported_skills)
    if missing:
        raise SystemExit(f"requested skills not found in run: {', '.join(sorted(missing))}")
    created = utc_now()
    manifest = {
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "created_at": created,
        "completed_at": created,
        "mode": args.mode,
        "formal": args.formal,
        "cycle": cycle,
        "proposal_type": args.proposal_type,
        "skills": imported_skills,
        "victims": sorted({cell["victim"] for cell in cells}),
        "goal_ids": sorted(goal_ids),
        "goal_file": None,
        "min_score_rate": 1.0,
        "selection_policy": "one_global_variant_across_full_victim_panel",
        "hypothesis": "",
        "notes": args.notes,
        "run_dir": repo_relative(run_dir),
        "status": "complete" if all(cell["status"] == "complete" for cell in cells) else "incomplete",
        "cells": cells,
        "imported": True,
    }
    manifest_path = MEMORY_DIR / "imports" / f"{evaluation_id}.json"
    atomic_write_json(manifest_path, manifest)
    register_evaluation(evaluation_entry(manifest, manifest_path))
    rebuild_index()
    if args.formal:
        consolidate_cycle(cycle)
    print(json.dumps({"evaluation_id": evaluation_id, "status": manifest["status"], "cells": len(cells)}))
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "rebuild":
        index = rebuild_index()
        print(json.dumps(index["statistics"], sort_keys=True))
        print(f"-> {repo_relative(MEMORY_INDEX)}")
        return 0
    if args.command == "consolidate":
        try:
            path = consolidate_cycle(args.cycle)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"-> {repo_relative(path)}")
        return 0
    if args.command == "import-run":
        return import_run_command(args)
    index = load_index()
    if args.command in ("goal", "records"):
        args.skill = list(dict.fromkeys(resolve_skill_id(value) for value in args.skill))
    elif args.command == "skill":
        args.skill_id = resolve_skill_id(args.skill_id)
    elif args.command == "list" and args.skill:
        args.skill = resolve_skill_id(args.skill)
    if args.command == "goal":
        return goal_command(index, args)
    if args.command == "records":
        return records_command(index, args)
    if args.command == "skill":
        return skill_command(index, args)
    if args.command == "evaluation":
        return evaluation_command(index, args)
    if args.command == "list":
        return list_command(index, args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
