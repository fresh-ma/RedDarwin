#!/usr/bin/env python3
"""Generate a genuine training_corpus for the CipherChat unit.

CipherChat's payload is DETERMINISTIC: there is no attacker LLM. Each harmful
request is enciphered with the official cipher (Caesar / Atbash / Morse / ASCII /
Unicode) or kept verbatim for SelfCipher, and wrapped in the official
cipher-expert system prompt (role + 3 enciphered unsafe demonstrations + the
prompt-injection trailer). This script reuses the real attack functions verbatim
(``attack.load_prompt_pack`` / ``attack.load_dataset`` / ``attack.resolve_cipher``
/ ``attack.build_messages``) — no reimplementation — to emit one genuine
enciphered attack payload per goal over the FULL bilingual safety bench, then
quality-filters and writes the SFT corpus. One cipher per goal is seed-assigned
(random.Random(seed)) from the paper's faithful cipher set, so the corpus is
fully reproducible given the same seed.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import attack  # noqa: E402  (sibling module in scripts/)

HERE = Path(__file__).resolve().parent
METHOD_DIR = HERE.parent
DATA = METHOD_DIR / "data"
PROMPTS = DATA / "official_prompts_pack.json"
DATASET = DATA / "cipherchat_safety_bench_en_zh.json"
OUT = DATA / "training_corpus" / "sft_cipherchat.json"

SEED = 20260629
MIN_CHARS = 15

# Faithful cipher set (paper's evaluated ciphers; excludes vanilla baseline).
CIPHERS = ["selfcipher", "caesar", "atbash", "morse", "ascii", "unicode"]

REFUSAL_PREFIXES = (
    "i'm sorry", "i am sorry", "sorry, but", "i cannot", "i can't", "i can not",
    "as an ai", "i'm unable", "i am unable", "i apologize", "i must decline",
)


def is_leading_refusal(text: str) -> bool:
    head = text.strip().lower()[:40]
    return any(head.startswith(p) for p in REFUSAL_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap goals (debug only)")
    args = parser.parse_args()

    pack = attack.load_prompt_pack(PROMPTS)
    rows_in = attack.load_dataset(DATASET)  # FULL bilingual set, deterministic order
    if args.limit:
        rows_in = rows_in[: args.limit]
    attempted = len(rows_in)

    rng = random.Random(SEED)

    rows: list[dict] = []
    drop_counts = {"empty": 0, "too_short": 0, "leading_refusal": 0,
                   "degenerate_echo": 0, "duplicate": 0, "build_error": 0}
    seen: set[str] = set()

    for idx, row in enumerate(rows_in):
        # Seed-assign one faithful cipher per goal (reproducible).
        cipher_name = rng.choice(CIPHERS)
        cipher_key = attack.resolve_cipher(cipher_name)
        try:
            messages = attack.build_messages(pack, cipher_key, row)
        except Exception:
            drop_counts["build_error"] += 1
            continue

        system = messages[0]["content"]
        enciphered_request = messages[1]["content"]
        # The deliverable payload = the full enciphered attack prompt the model sees.
        attack_prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{enciphered_request}"

        if not attack_prompt.strip() or not enciphered_request.strip():
            drop_counts["empty"] += 1
            continue
        if len(attack_prompt) < MIN_CHARS:
            drop_counts["too_short"] += 1
            continue
        # Genuine encoding ciphers must actually transform the request; SelfCipher
        # (unchange) keeps it verbatim by design, so the echo check is cipher-aware.
        if cipher_key not in ("unchange", "baseline") and enciphered_request.strip() == row["request"].strip():
            drop_counts["degenerate_echo"] += 1
            continue
        if is_leading_refusal(attack_prompt):
            drop_counts["leading_refusal"] += 1
            continue
        if attack_prompt in seen:
            drop_counts["duplicate"] += 1
            continue
        seen.add(attack_prompt)

        rows.append({
            "case_id": f"{idx:04d}",
            "goal": row["request"],
            "lang": row["lang"],
            "demo_domain": row["demo_domain"],
            "category": row["category"],
            "cipher": cipher_key,
            "cipher_label": "selfcipher" if cipher_key == "unchange" else cipher_key,
            "system_prompt": system,
            "enciphered_request": enciphered_request,
            "attack_prompt": attack_prompt,
        })

    header = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_NAME,
        "generator_model": "deterministic_cipher_procedure (no attacker LLM; official RobustNLP/CipherChat encode_experts + official prompt pack)",
        "generator_note": (
            "Deterministic CipherChat jailbreak: NO attacker LLM. Per-goal payload = "
            "attack.build_messages(pack, cipher, row) — the official cipher-expert "
            "system prompt (role + 3 enciphered unsafe demonstrations + prompt-injection "
            "trailer) plus the request enciphered with the official cipher. One cipher per "
            "goal is seed-assigned (random.Random(seed)) from the paper's faithful set: "
            "SelfCipher/Caesar/Atbash/Morse/ASCII/Unicode. Ciphers and prompt assembly are "
            "imported verbatim from attack.py / encode_experts.py; fully reproducible given "
            "the same seed."
        ),
        "payload_field": "attack_prompt",
        "source_dataset": str(DATASET.relative_to(METHOD_DIR)),
        "ciphers": CIPHERS,
        "count": len(rows),
        "dropped": attempted - len(rows),
        "drop_counts": drop_counts,
        "total_attempted": attempted,
        "distinct_outputs": len({r["attack_prompt"] for r in rows}),
        "seed": SEED,
        "rows": rows,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"attempted={attempted} kept={len(rows)} dropped={attempted - len(rows)} "
          f"distinct={header['distinct_outputs']} drops={drop_counts}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
