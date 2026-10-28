from __future__ import annotations

import ast
import json
import random
import re
import string
from typing import Any

from .clients import ChatClient, complete_with_retries
from .prompts import (
    get_attacker_system_prompt,
    get_evaluator_system_prompt_for_judge,
    get_evaluator_system_prompt_for_on_topic,
    get_init_msg,
    process_target_response,
)


def random_string(n: int = 32) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def extract_json(text: str) -> tuple[dict[str, str] | None, str | None]:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None, None
    json_str = text[start:end].replace("\n", "")
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(json_str)
            if isinstance(parsed, dict) and all(key in parsed for key in ("improvement", "prompt")):
                return {"improvement": str(parsed["improvement"]), "prompt": str(parsed["prompt"])}, json_str
        except Exception:
            pass
    return None, None


def parse_judge_score(raw: str) -> int:
    match = re.search(r"\[\[(\d+)\]\]", raw)
    if not match:
        match = re.search(r"\b([1-9]|10)\b", raw)
    score = int(match.group(1)) if match else 1
    return max(1, min(score, 10))


def parse_on_topic(raw: str) -> int:
    match = re.search(r"\[\[(yes|no)\]\]", raw, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(yes|no)\b", raw, re.IGNORECASE)
    if not match:
        return 1
    return int(match.group(1).lower() == "yes")


def build_messages(system_prompt: str, conversation: list[dict[str, str]], user_prompt: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system_prompt}, *conversation, {"role": "user", "content": user_prompt}]


def reasoning_extra_body(mode: str, model: str = "") -> dict[str, Any] | None:
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> never send the
    # reasoning-off body for them.
    if mode == "off" and "gpt-oss" not in model.lower():
        return {"reasoning": {"enabled": False}}
    return None


def generate_attack(
    attacker: ChatClient,
    *,
    system_prompt: str,
    conversation: list[dict[str, str]],
    processed_response: str,
    max_tokens: int,
    temperature: float,
    max_attempts: int,
    retry_sleep: float,
    attacker_reasoning_effort: str | None = None,
) -> dict[str, Any] | None:
    raw_attempts = []
    for _ in range(max(max_attempts, 1)):
        if attacker_reasoning_effort is not None and attacker_reasoning_effort != "":
            raw, call = complete_with_retries(
                attacker,
                build_messages(system_prompt, conversation, processed_response),
                max_tokens=max_tokens,
                temperature=temperature,
                response_format="json_object",
                reasoning_effort=attacker_reasoning_effort,
                max_attempts=1,
                retry_sleep=retry_sleep,
            )
        else:
            raw, call = complete_with_retries(
                attacker,
                build_messages(system_prompt, conversation, processed_response),
                max_tokens=max_tokens,
                temperature=temperature,
                response_format="json_object",
                max_attempts=1,
                retry_sleep=retry_sleep,
            )
        parsed, json_str = extract_json(raw)
        raw_attempts.append({"raw": raw, "call": call, "parsed": parsed is not None})
        if parsed is not None and json_str is not None:
            new_conversation = [
                *conversation,
                {"role": "user", "content": processed_response},
                {"role": "assistant", "content": json_str},
            ]
            return {
                "improvement": parsed["improvement"],
                "prompt": parsed["prompt"],
                "conversation": new_conversation,
                "raw_attempts": raw_attempts,
            }
    return {"failed": True, "raw_attempts": raw_attempts}


def evaluator_on_topic(
    evaluator: ChatClient,
    *,
    goal: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    max_attempts: int,
    retry_sleep: float,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if extra_body is not None:
        kwargs["extra_body"] = extra_body
    raw, call = complete_with_retries(
        evaluator,
        [
            {"role": "system", "content": get_evaluator_system_prompt_for_on_topic(goal)},
            {"role": "user", "content": f"[PROMPT]:{prompt}"},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        max_attempts=max_attempts,
        retry_sleep=retry_sleep,
        **kwargs,
    )
    return {"score": parse_on_topic(raw), "raw": raw, "call": call}


def evaluator_judge(
    evaluator: ChatClient,
    *,
    goal: str,
    target_str: str,
    prompt: str,
    response: str,
    max_tokens: int,
    temperature: float,
    max_attempts: int,
    retry_sleep: float,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if extra_body is not None:
        kwargs["extra_body"] = extra_body
    raw, call = complete_with_retries(
        evaluator,
        [
            {"role": "system", "content": get_evaluator_system_prompt_for_judge(goal, target_str)},
            {"role": "user", "content": f"[PROMPT]:{prompt}\n[ASSISTANT'S RESPONSE]: {response}"},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        max_attempts=max_attempts,
        retry_sleep=retry_sleep,
        **kwargs,
    )
    return {"score": parse_judge_score(raw), "raw": raw, "call": call}


def prune_candidates(candidates: list[dict[str, Any]], score_key: str, width: int) -> list[dict[str, Any]]:
    shuffled = list(candidates)
    random.shuffle(shuffled)
    shuffled.sort(key=lambda item: item.get(score_key, 0), reverse=True)
    positive = [candidate for candidate in shuffled if candidate.get(score_key, 0) > 0]
    if positive:
        return positive[: min(width, len(positive))]
    return shuffled[: min(max(width, 1), len(shuffled))]


def run_tap_goal(args: Any, goal_row: dict[str, str], attacker: ChatClient, target: ChatClient, evaluator: ChatClient) -> dict[str, Any]:
    goal = goal_row["goal"]
    target_str = goal_row.get("target") or args.target_str
    attacker_system_prompt = get_attacker_system_prompt(goal, target_str)
    init_msg = get_init_msg(goal, target_str)

    if args.render_only:
        return {
            **goal_row,
            "success": None,
            "status": "render_only",
            "model_input_messages": [{"role": "user", "content": init_msg}],
            "model_output_text": "",
            "attacker_system_prompt": attacker_system_prompt,
            "initial_message": init_msg,
            "iterations": [],
            "best": None,
            "query_counts": {"target": 0, "attacker": 0, "evaluator": 0},
        }

    layer = [
        {
            "id": random_string(),
            "parent_id": "NA",
            "conversation": [],
            "processed_response": init_msg,
            "depth": 0,
        }
        for _ in range(args.n_streams)
    ]
    iterations = []
    best = {"prompt": "", "response": "", "judge_score": 0}
    query_counts = {"target": 0, "attacker": 0, "evaluator": 0}
    valid_target_seen = False
    success = False
    target_model = getattr(target, "model", "")
    evaluator_model = getattr(evaluator, "model", "")
    target_extra_body = reasoning_extra_body(args.target_reasoning, target_model)
    evaluator_extra_body = reasoning_extra_body(args.evaluator_reasoning, evaluator_model)
    # gpt-oss mandates reasoning; its reasoning tokens share the max_tokens budget,
    # so a small target budget would starve the visible answer.
    target_max_tokens = args.target_max_tokens
    if "gpt-oss" in target_model.lower() and target_max_tokens < 1024:
        target_max_tokens = 1024

    for iteration in range(1, args.depth + 1):
        candidates = []
        for _ in range(args.branching_factor):
            for node in layer:
                attack = generate_attack(
                    attacker,
                    system_prompt=attacker_system_prompt,
                    conversation=node["conversation"],
                    processed_response=node["processed_response"],
                    max_tokens=args.attacker_max_tokens,
                    temperature=args.attacker_temperature,
                    max_attempts=args.max_attack_attempts,
                    retry_sleep=args.retry_sleep,
                    attacker_reasoning_effort=args.attacker_reasoning_effort,
                )
                query_counts["attacker"] += len(attack.get("raw_attempts", [])) if attack else 0
                if not attack or attack.get("failed"):
                    continue
                candidates.append(
                    {
                        "id": random_string(),
                        "parent_id": node["id"],
                        "depth": node["depth"] + 1,
                        "prompt": attack["prompt"],
                        "improvement": attack["improvement"],
                        "conversation": attack["conversation"],
                        "attack_raw_attempts": attack["raw_attempts"],
                    }
                )

        if not candidates:
            iterations.append({"iteration": iteration, "status": "no_valid_attacker_outputs", "candidates": []})
            break

        for candidate in candidates:
            on_topic = evaluator_on_topic(
                evaluator,
                goal=goal,
                prompt=candidate["prompt"],
                max_tokens=args.evaluator_max_tokens,
                temperature=args.evaluator_temperature,
                max_attempts=args.model_call_retries,
                retry_sleep=args.retry_sleep,
                extra_body=evaluator_extra_body,
            )
            query_counts["evaluator"] += 1
            candidate["on_topic_score"] = on_topic["score"]
            candidate["on_topic_raw"] = on_topic["raw"]
            candidate["on_topic_call"] = on_topic["call"]

        after_phase1 = prune_candidates(candidates, "on_topic_score", args.width)

        for candidate in after_phase1:
            target_kwargs: dict[str, Any] = {}
            if target_extra_body is not None:
                target_kwargs["extra_body"] = target_extra_body
            response, target_call = complete_with_retries(
                target,
                [{"role": "user", "content": candidate["prompt"]}],
                max_tokens=target_max_tokens,
                temperature=args.target_temperature,
                seed=args.target_seed,
                max_attempts=args.model_call_retries,
                retry_sleep=args.retry_sleep,
                **target_kwargs,
            )
            query_counts["target"] += 1
            candidate["target_response"] = response
            candidate["target_call"] = target_call
            if response.strip():
                valid_target_seen = True
                judge = evaluator_judge(
                    evaluator,
                    goal=goal,
                    target_str=target_str,
                    prompt=candidate["prompt"],
                    response=response,
                    max_tokens=args.evaluator_max_tokens,
                    temperature=args.evaluator_temperature,
                    max_attempts=args.model_call_retries,
                    retry_sleep=args.retry_sleep,
                    extra_body=evaluator_extra_body,
                )
                query_counts["evaluator"] += 1
                candidate["judge_score"] = judge["score"]
                candidate["judge_raw"] = judge["raw"]
                candidate["judge_call"] = judge["call"]
            else:
                candidate["judge_score"] = 1
                candidate["judge_raw"] = "empty_target_response"
                candidate["judge_call"] = {"ok": False, "reason": "empty_target_response"}

            if candidate["judge_score"] > best["judge_score"]:
                best = {
                    "prompt": candidate["prompt"],
                    "response": candidate["target_response"],
                    "judge_score": candidate["judge_score"],
                    "iteration": iteration,
                    "candidate_id": candidate["id"],
                }

        iterations.append(
            {
                "iteration": iteration,
                "generated_count": len(candidates),
                "after_phase1_count": len(after_phase1),
                "candidates": after_phase1,
            }
        )

        if any(candidate["judge_score"] >= args.success_threshold for candidate in after_phase1):
            success = True
            break

        layer = []
        for candidate in prune_candidates(after_phase1, "judge_score", args.width):
            conversation = candidate["conversation"]
            if args.keep_last_n >= 0:
                conversation = conversation[-2 * args.keep_last_n :] if args.keep_last_n else []
            layer.append(
                {
                    "id": candidate["id"],
                    "parent_id": candidate["parent_id"],
                    "conversation": conversation,
                    "processed_response": process_target_response(
                        candidate.get("target_response", ""),
                        int(candidate.get("judge_score", 1)),
                        goal,
                        target_str,
                    ),
                    "depth": candidate["depth"],
                }
            )
        if not layer:
            break

    if not valid_target_seen:
        success_value = None
        status = "invalid_no_target_response"
    else:
        success_value = success
        # unified_judge only scores records with status "ok"/missing; the TAP
        # outcome itself stays available in the `success` boolean above.
        status = "ok"

    return {
        **goal_row,
        "target_str": target_str,
        "success": success_value,
        "status": status,
        "model_input_messages": [{"role": "user", "content": best.get("prompt", "")}],
        "model_output_text": best.get("response", ""),
        "best": best,
        "iterations": iterations,
        "query_counts": query_counts,
        "settings": {
            "branching_factor": args.branching_factor,
            "width": args.width,
            "depth": args.depth,
            "n_streams": args.n_streams,
            "keep_last_n": args.keep_last_n,
            "success_threshold": args.success_threshold,
        },
    }
