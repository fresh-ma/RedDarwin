#!/usr/bin/env python3
"""Validate a run before publishing its cross-victim leaderboard.

The validator rejects missing or duplicate attack/victim cells, malformed
unified summaries, undersized outputs, and low judge coverage. On success it
can write a manifest that pins every selected result by filename and SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_VICTIMS = "qwen/qwen3.7-flash,openai/gpt-oss-120b,deepseek/deepseek-v4-flash-0731,openai/gpt-5.6-luna"


def csv_values(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def result_identity(name: str, slug_to_victim: dict[str, str]) -> tuple[str, str] | None:
    stem = name[: -len(".judged.json")]
    for slug, victim in slug_to_victim.items():
        marker = f"_{slug}_"
        if marker in stem:
            return stem.split(marker, 1)[0], victim
    return None


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--attacks", required=True, help="Comma-separated required attack IDs")
    parser.add_argument("--victims", default=DEFAULT_VICTIMS)
    parser.add_argument("--min-items", type=int, default=1)
    parser.add_argument(
        "--expected-goals",
        type=int,
        default=0,
        help="Benchmark goal count; caps the coverage denominator (0 disables the cap)",
    )
    parser.add_argument("--min-score-rate", type=float, default=0.8)
    parser.add_argument("--out-manifest", default="")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    attacks = csv_values(args.attacks)
    victims = csv_values(args.victims)
    errors: list[str] = []

    if not results_dir.is_dir():
        errors.append(f"results directory does not exist: {results_dir}")
    if not attacks:
        errors.append("at least one required attack is needed")
    if not victims:
        errors.append("at least one victim is needed")
    if args.min_items < 1:
        errors.append("--min-items must be at least 1")
    if args.expected_goals < 0:
        errors.append("--expected-goals cannot be negative")
    if not 0 <= args.min_score_rate <= 1:
        errors.append("--min-score-rate must be between 0 and 1")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    slug_to_victim = {victim.split("/")[-1]: victim for victim in victims}
    cells: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(results_dir.glob("*.judged.json")):
        identity = result_identity(path.name, slug_to_victim)
        if identity is None:
            errors.append(f"unrecognized victim slug: {path.name}")
            continue
        cells.setdefault(identity, []).append(path)

    all_attacks = sorted(set(attacks) | {attack for attack, _ in cells})
    records: list[dict[str, object]] = []
    for attack in all_attacks:
        for victim in victims:
            matches = cells.get((attack, victim), [])
            label = f"{attack} x {victim}"
            if not matches:
                errors.append(f"missing result: {label}")
                continue
            if len(matches) > 1:
                names = ", ".join(path.name for path in matches)
                errors.append(f"duplicate results: {label}: {names}")
                continue

            path = matches[0]
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"cannot read {path.name}: {exc}")
                continue
            summary = data.get("unified_summary")
            if not isinstance(summary, dict):
                errors.append(f"missing unified_summary: {path.name}")
                continue

            asr = summary.get("asr")
            n = summary.get("n")
            n_scored = summary.get("n_scored")
            if not is_number(asr) or not 0 <= asr <= 1:
                errors.append(f"invalid ASR in {path.name}: {asr!r}")
            if not isinstance(n, int) or isinstance(n, bool) or n < args.min_items:
                errors.append(
                    f"too few items in {path.name}: n={n!r}, minimum={args.min_items}"
                )
            if (
                not isinstance(n_scored, int)
                or isinstance(n_scored, bool)
                or not isinstance(n, int)
                or n_scored < 1
                or n_scored > n
            ):
                errors.append(f"invalid score count in {path.name}: {n_scored!r}/{n!r}")
            else:
                coverage_target = min(n, args.expected_goals) if args.expected_goals else n
            if (
                isinstance(n_scored, int)
                and not isinstance(n_scored, bool)
                and isinstance(n, int)
                and n_scored >= 1
                and n_scored <= n
                and n_scored / coverage_target < args.min_score_rate
            ):
                errors.append(
                    f"low judge coverage in {path.name}: {n_scored}/{coverage_target} "
                    f"<{args.min_score_rate:.0%}"
                )

            records.append(
                {
                    "attack": attack,
                    "victim": victim,
                    "file": path.name,
                    "sha256": sha256(path),
                    "unified_summary": summary,
                }
            )

    if errors:
        print(f"leaderboard validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    manifest = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "results_dir": str(results_dir),
        "constraints": {
            "min_items": args.min_items,
            "expected_goals": args.expected_goals,
            "min_score_rate": args.min_score_rate,
        },
        "victims": victims,
        "attacks": all_attacks,
        "results": records,
    }
    if args.out_manifest:
        output = Path(args.out_manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        print(f"manifest: {output}")
    print(
        f"leaderboard validation passed: {len(all_attacks)} attacks x "
        f"{len(victims)} victims = {len(records)} results"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
