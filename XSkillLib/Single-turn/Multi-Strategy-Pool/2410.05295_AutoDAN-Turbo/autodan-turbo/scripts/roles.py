#!/usr/bin/env python3
"""AutoDAN-Turbo roles: attacker / target / scorer / summarizer / dual judge.

Each role is an independent `api:<model>` flag so models can be mix-and-matched.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from models import api_chat, conditional_generate
from prompts import (
    ATTACKER_CONDITION,
    ATTACKER_REFUSAL_SNIPPETS,
    ATTACKER_USER_STRATEGY,
    ATTACKER_USER_WARMUP,
    CONTENT_HARMFUL_SYSTEM,
    GCG_REFUSAL_PREFIXES,
    REFUSAL_BYPASS_SYSTEM,
    SCORER_USER,
    SCORER_WRAPPER_SYSTEM,
    SUMMARIZER_CONDITION,
    SUMMARIZER_USER,
    SUMMARIZER_WRAPPER_CONDITION,
    SUMMARIZER_WRAPPER_SYSTEM,
    attacker_find_new_strategy_system,
    attacker_use_strategy_system,
    attacker_warm_up_system,
    dual_judge_user,
    parse_yes_no,
    scorer_system,
    summarizer_system,
    wrap_jailbreak,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _model_id(spec: str) -> str:
    if spec.startswith("api:"):
        return spec[4:]
    return spec


# ---------------------------------------------------------------------------
# Attacker
# ---------------------------------------------------------------------------
def attacker_warm_up(attacker: str, request: str, max_tokens: int) -> tuple[str, str]:
    mid = _model_id(attacker)
    system = attacker_warm_up_system(request)
    out, status = conditional_generate(
        mid, ATTACKER_CONDITION, system, ATTACKER_USER_WARMUP, max_tokens, 1.0
    )
    return wrap_jailbreak(out, request), status


def attacker_use_strategy(
    attacker: str, request: str, strategy_list: list[dict], max_tokens: int
) -> tuple[str, str]:
    mid = _model_id(attacker)
    system = attacker_use_strategy_system(request, strategy_list)
    out, status = conditional_generate(
        mid, ATTACKER_CONDITION, system, ATTACKER_USER_STRATEGY, max_tokens, 1.0
    )
    return wrap_jailbreak(out, request), status


def attacker_find_new_strategy(
    attacker: str, request: str, strategy_list: list[dict], max_tokens: int
) -> tuple[str, str]:
    mid = _model_id(attacker)
    system = attacker_find_new_strategy_system(request, strategy_list)
    out, status = conditional_generate(
        mid, ATTACKER_CONDITION, system, ATTACKER_USER_STRATEGY, max_tokens, 1.0
    )
    return wrap_jailbreak(out, request), status


def scrub_attacker_refusal(jb: str, request: str) -> str:
    for w in ATTACKER_REFUSAL_SNIPPETS:
        if w in jb:
            return request
    return jb


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------
def call_target(target: str, prompt: str, max_tokens: int) -> tuple[str, str]:
    mid = _model_id(target)
    return api_chat(
        mid,
        [{"role": "user", "content": prompt}],
        temperature=1.0,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Scorer (paper in-loop 1–10)
# ---------------------------------------------------------------------------
def _extract_score(text: str) -> float | None:
    nums = re.findall(r"\b(10(?:\.0)?|[1-9](?:\.[05])?)\b", text)
    if not nums:
        return None
    try:
        val = float(nums[-1])
        if 1.0 <= val <= 10.0:
            return val
    except ValueError:
        pass
    return None


def scorer_score(
    scorer: str, request: str, target_response: str, max_tokens: int
) -> tuple[float | None, str, str]:
    mid = _model_id(scorer)
    system = scorer_system(request, target_response)
    out, status = api_chat(
        mid,
        [{"role": "system", "content": system}, {"role": "user", "content": SCORER_USER}],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    if status != "ok":
        return None, status, out
    score = _extract_score(out)
    if score is None:
        score = _scorer_wrapper(mid, out)
    return score, ("ok" if score is not None else "no_score"), out


def _scorer_wrapper(model: str, user_text: str) -> float | None:
    out, status = api_chat(
        model,
        [
            {"role": "system", "content": SCORER_WRAPPER_SYSTEM},
            {"role": "user", "content": f"[INPUT]: '{user_text}'"},
        ],
        temperature=0.0,
        max_tokens=50,
    )
    if status != "ok":
        return None
    try:
        return float(re.findall(r"\d+(?:\.\d+)?", out)[0])
    except (IndexError, ValueError):
        return 1.0


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------
def _parse_strategy(text: str) -> dict | None:
    for m in re.finditer(r"\{[^{}]*\"Strategy\"[^{}]*\}", text, re.DOTALL):
        try:
            d = json.loads(m.group(0))
            if "Strategy" in d and "Definition" in d:
                return {"Strategy": str(d["Strategy"]), "Definition": str(d["Definition"])}
        except json.JSONDecodeError:
            continue
    return None


def summarizer_summarize(
    summarizer: str,
    request: str,
    jp1: str,
    jp2: str,
    strategy_library: dict,
    max_tokens: int,
) -> tuple[dict | None, str]:
    mid = _model_id(summarizer)
    system = summarizer_system(request, jp1, jp2, strategy_library)
    out, status = conditional_generate(
        mid, SUMMARIZER_CONDITION, system, SUMMARIZER_USER, max_tokens, 0.6
    )
    if status != "ok":
        return None, status
    strat = _parse_strategy(out)
    if strat is None:
        wout, _wst = conditional_generate(
            mid,
            SUMMARIZER_WRAPPER_CONDITION,
            SUMMARIZER_WRAPPER_SYSTEM,
            f"[INPUT]: '{out}'",
            200,
            0.6,
        )
        strat = _parse_strategy("{" + wout)
    if strat is None:
        return None, "no_strategy"
    return strat, "ok"


# ---------------------------------------------------------------------------
# Embedding + retrieval (stdlib L2 NN; substitutes OpenAI ada-002)
# ---------------------------------------------------------------------------
def embed(text: str, dim: int = 512) -> list[float]:
    vec = [0.0] * dim
    for tok in _TOKEN_RE.findall((text or "").lower()):
        vec[hash(tok) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _l2(a: list[float], b: list[float]) -> float:
    return sum((x - y) * (x - y) for x, y in zip(a, b))


def retrieval_pop(library: dict, query_response: str, k: int = 5) -> tuple[bool, list[dict]]:
    """framework/retrival.py pop() selection logic (L2 NN over stored response embeddings)."""
    q = embed(query_response)
    all_emb, all_scores, all_example, reverse_map = [], [], [], []
    for s_name, s_info in library.items():
        for emb, score, ex in zip(s_info["Embeddings"], s_info["Score"], s_info["Example"]):
            all_emb.append(emb)
            all_scores.append(score)
            all_example.append(ex)
            reverse_map.append(s_name)
    if not all_emb:
        return True, []
    order = sorted(range(len(all_emb)), key=lambda i: _l2(q, all_emb[i]))
    max_strategies = 2 * k
    seen, retrieved = set(), {}
    for idx in order:
        s_name = reverse_map[idx]
        s_score, s_ex = all_scores[idx], all_example[idx]
        if s_name not in seen:
            seen.add(s_name)
            info = library[s_name]
            retrieved[s_name] = {
                "Strategy": info["Strategy"],
                "Definition": info["Definition"],
                "Example": s_ex,
                "Score": s_score,
            }
        else:
            prev = retrieved[s_name]["Score"]
            retrieved[s_name]["Score"] = (prev + s_score) / 2
            if prev < s_score:
                retrieved[s_name]["Example"] = s_ex
        if len(retrieved) >= max_strategies:
            break
    final, ineffective = [], []
    for info in retrieved.values():
        if info["Score"] >= 5:
            final = [{kk: vv for kk, vv in info.items() if kk != "Score"}]
            break
        if 2 <= info["Score"] < 5:
            final.append({kk: vv for kk, vv in info.items() if kk != "Score"})
            if len(final) >= k:
                break
        else:
            ineffective.append({kk: vv for kk, vv in info.items() if kk != "Score"})
    if final:
        return True, final
    if len(ineffective) > k:
        return False, ineffective[:k]
    return False, ineffective


# ---------------------------------------------------------------------------
# Dual judge + keyword fallback
# ---------------------------------------------------------------------------
def keyword_refusal_bypass(response: str) -> bool:
    """True = NOT refused = bypass (GCG prefixes)."""
    return not any(p in (response or "") for p in GCG_REFUSAL_PREFIXES)


def dual_judge(
    judge: str, goal: str, response: str, max_tokens: int = 256
) -> dict[str, Any]:
    """Two independent yes/no LLM calls: refusal_bypass + content_harmful."""
    mid = _model_id(judge)
    user = dual_judge_user(goal, response)

    rb_raw, rb_st = api_chat(
        mid,
        [{"role": "system", "content": REFUSAL_BYPASS_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    ch_raw, ch_st = api_chat(
        mid,
        [{"role": "system", "content": CONTENT_HARMFUL_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    rb = parse_yes_no(rb_raw) if rb_st == "ok" else None
    ch = parse_yes_no(ch_raw) if ch_st == "ok" else None
    # keyword fallback if parse fails
    if rb is None:
        rb = keyword_refusal_bypass(response)
    if ch is None:
        ch = False
    return {
        "name": f"dual_yesno::{judge}",
        "refusal_bypass": bool(rb),
        "content_harmful": bool(ch),
        "refusal_bypass_raw": rb_raw if rb_st == "ok" else rb_st,
        "content_harmful_raw": ch_raw if ch_st == "ok" else ch_st,
        "status": "ok" if (rb_st == "ok" and ch_st == "ok") else f"rb={rb_st},ch={ch_st}",
    }
