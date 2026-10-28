#!/usr/bin/env python3
"""Aggregate per-attack judged results into a cross-victim ASR leaderboard.

Scans a results directory for `*.judged.json` files produced by scripts/*.sh
(filename convention: <attack>_<victim-slug>_<setting>_<N>x_<stamp>.judged.json),
reads each file's `unified_summary`, and emits a markdown table + JSON with one
row per attack and one column per victim, sorted by mean ASR.

Usage:
  python leaderboard.py --results-dir runs/<stamp>/results \
      [--victims qwen/qwen3.7-flash,openai/gpt-oss-120b,deepseek/deepseek-v4-flash] \
      [--out-md leaderboard.md] [--out-json leaderboard.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_VICTIMS = "qwen/qwen3.7-flash,openai/gpt-oss-120b,deepseek/deepseek-v4-flash-0731,openai/gpt-5.6-luna"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--victims", default=DEFAULT_VICTIMS)
    ap.add_argument("--out-md", default="")
    ap.add_argument("--out-json", default="")
    args = ap.parse_args()

    victims = [v.strip() for v in args.victims.split(",") if v.strip()]
    slug_to_victim = {v.split("/")[-1]: v for v in victims}

    rows: dict[str, dict[str, dict]] = {}
    skipped: list[str] = []
    for f in sorted(Path(args.results_dir).glob("*.judged.json")):
        stem = f.name[: -len(".judged.json")]
        match = None
        for slug in slug_to_victim:
            marker = f"_{slug}_"
            if marker in stem:
                match = (stem.split(marker)[0], slug)
                break
        if not match:
            skipped.append(f.name)
            continue
        attack, slug = match
        data = json.loads(f.read_text(encoding="utf-8"))
        summ = data.get("unified_summary") or {}
        rows.setdefault(attack, {})[slug_to_victim[slug]] = {
            "asr": summ.get("asr"),
            "n_scored": summ.get("n_scored"),
            "n": summ.get("n"),
            "mean_score": summ.get("mean_score"),
        }

    table = []
    for attack, per in rows.items():
        vals = [v["asr"] for v in per.values() if v.get("asr") is not None]
        mean = round(sum(vals) / len(vals), 4) if vals else None
        table.append({"attack": attack, "per_victim": per, "mean_asr": mean})
    table.sort(key=lambda r: (r["mean_asr"] is None, -(r["mean_asr"] or 0.0)))

    def cell(entry: dict | None) -> str:
        if not entry or entry.get("asr") is None:
            return "—"
        ns, n = entry.get("n_scored"), entry.get("n")
        cnt = f" ({round(entry['asr'] * ns)}/{ns})" if isinstance(ns, int) and ns else ""
        return f"{entry['asr']:.3f}{cnt}"

    short = {v: v.split("/")[-1] for v in victims}
    lines = [
        "# ASR Leaderboard",
        "",
        f"Source: `{args.results_dir}` · judge: unified 1-5 rubric (score==5 => success)"
        f" · generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z",
        "",
        "| Rank | Attack | " + " | ".join(short[v] for v in victims) + " | Mean |",
        "|---:|---|" + "---:|" * (len(victims) + 1),
    ]
    for i, row in enumerate(table, 1):
        cells = [cell(row["per_victim"].get(v)) for v in victims]
        mean = f"{row['mean_asr']:.3f}" if row["mean_asr"] is not None else "—"
        lines.append(f"| {i} | {row['attack']} | " + " | ".join(cells) + f" | {mean} |")
    md = "\n".join(lines) + "\n"

    out_md = args.out_md or str(Path(args.results_dir) / "leaderboard.md")
    out_json = args.out_json or str(Path(args.results_dir) / "leaderboard.json")
    Path(out_md).write_text(md, encoding="utf-8")
    Path(out_json).write_text(json.dumps({
        "results_dir": args.results_dir,
        "victims": victims,
        "generated": datetime.now(timezone.utc).isoformat(),
        "skipped_files": skipped,
        "leaderboard": table,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    if skipped:
        print(f"note: {len(skipped)} file(s) had no known victim slug and were skipped: "
              f"{skipped[:5]}", file=sys.stderr)
    print(f"-> {out_md}\n-> {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
