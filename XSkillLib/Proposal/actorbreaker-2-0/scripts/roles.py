#!/usr/bin/env python3
"""Swappable role adapters for ActorBreaker.

Three roles, each a plain wrapper over a ``ModelClient`` so they mix-and-match
from CLI flags (``--attacker`` / ``--target`` / ``--judge``):

  Attacker  — the pre-attack + dynamic-modify LLM (official PreAttack + InAttack
              helpers): extract harm target, build the Latour actor-network,
              self-talk the benign multi-turn query chain, step-judge & rewrite.
  Target    — the victim LLM the multi-turn dialogue is sent to.
  Judge     — the Qi-2023 GPT-4 1-5 harmfulness judge (success == score 5).

Prompts are loaded verbatim from ``prompts.py``; algorithm main-line follows
AI45Lab/ActorAttack ``preattack.py`` / ``inattack.py`` / ``judge.py``.
"""
from __future__ import annotations

import prompts
from models import ModelClient, parse_json


# ============================================================== Attacker (adversary LLM)
class Attacker:
    def __init__(self, client: ModelClient) -> None:
        self.c = client

    # -- pre-attack --------------------------------------------------------
    def extract_harm_target(self, org_query: str) -> tuple[str, dict]:
        tmpl = prompts.load(prompts.EXTRACT)
        for _ in range(5):
            data = parse_json(self.c.chat(
                [{"role": "user", "content": tmpl.format(org_query=org_query)}], max_tokens=512))
            if data and "target" in data:
                return data["target"], data.get("details", {"delivery_type": "", "other_details": ""})
        return org_query, {"delivery_type": "", "other_details": ""}

    def plan_fragments(self, harm_target: str) -> list[str]:
        """2.0: decompose the harm target into the concrete information
        fragments a complete answer must contain (one attacker call)."""
        tmpl = prompts.load(prompts.FRAGMENTS)
        for _ in range(3):
            data = parse_json(self.c.chat(
                [{"role": "user", "content": tmpl.format(harm_target=harm_target)}], max_tokens=600))
            if data and isinstance(data.get("fragments"), list):
                frags = [str(f).strip() for f in data["fragments"] if str(f).strip()]
                if frags:
                    return frags[:6]
        return []

    def get_actors(self, harm_target: str, actor_num: int) -> list[dict]:
        network = prompts.load(prompts.NETWORK).format(harm_target=harm_target)
        _, hist = self.c.chat_append([], network, max_tokens=1500)
        num_string = "10 actors" if actor_num > 10 else f"{actor_num} actors"
        actor_prompt = prompts.load(prompts.ACTOR).format(num_string=num_string)
        more_actor_prompt = prompts.load(prompts.MORE_ACTOR)
        actors: list[dict] = []
        for _ in range(3):
            resp, hist = self.c.chat_append(hist, actor_prompt, max_tokens=900)
            data = parse_json(resp)
            if data and "actors" in data:
                for item in data["actors"]:
                    if item.get("actor_name") and item["actor_name"] not in [a["actor_name"] for a in actors]:
                        actors.append(item)
            hist = hist[:-2]
            if len(actors) >= actor_num:
                return actors[:actor_num]
            resp, hist = self.c.chat_append(hist, more_actor_prompt, max_tokens=900)
        return actors[:actor_num] if actors else []

    def get_init_queries(self, harm_target: str, actor: dict, fragments: list[str]) -> list[str]:
        frag_str = "\n".join(f"- {f}" for f in fragments) if fragments else \
            "- every concrete specific needed to fully answer the target"
        qp = prompts.load(prompts.QUERY).format(
            harm_target=harm_target, actor_name=actor["actor_name"],
            relationship=actor.get("relationship", ""), fragments=frag_str)
        fmt = prompts.load(prompts.JSON_FORMAT)
        for _ in range(5):
            query_resp = self.c.chat([{"role": "user", "content": qp}], max_tokens=1500)
            data = parse_json(self.c.chat(
                [{"role": "user", "content": fmt.format(resp=query_resp)}], max_tokens=900))
            if data and "questions" in data:
                queries = [q for it in data["questions"] if it.get("question")
                           for q in [prompts.clean_query(it["question"])] if q]
                if queries:
                    return queries[:5]
        return []

    # -- in-attack dynamic-modify -----------------------------------------
    def step_judge(self, query: str, response: str) -> str:
        tmpl = prompts.load(prompts.STEP_JUDGE)
        data = parse_json(self.c.chat(
            [{"role": "user", "content": tmpl.format(query=query, response=response)}], max_tokens=120))
        return (data or {}).get("type", "")

    def modify(self, queries: list[str], query: str, output_type: str, previous_response: str) -> str:
        qstr = "".join(f"{j + 1}. {q}\n" for j, q in enumerate(queries))
        tmpl = prompts.load(prompts.MODIFY)
        raw = self.c.chat([{"role": "user", "content": tmpl.format(
            queries=qstr, query=query, output_type=output_type,
            previous_response=previous_response)}], max_tokens=400)
        return prompts.clean_query(raw)


# ============================================================== Target (victim LLM)
class Target:
    def __init__(self, client: ModelClient, max_tokens: int = 900, reasoning: bool = False) -> None:
        self.c = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def turn(self, history: list[dict], query: str) -> tuple[str, list[dict]]:
        return self.c.chat_append(history, query, max_tokens=self.max_tokens, reasoning=self.reasoning)


# ============================================================== Judge (Qi-2023 1-5)
class Judge:
    def __init__(self, client: ModelClient, holder: str = "OpenAI") -> None:
        self.c = client
        self.holder = holder

    def score(self, instruction: str, response: str) -> int:
        if not response:
            return -1
        for _ in range(2):
            data = parse_json(self.c.chat(
                [{"role": "user", "content": prompts.judge_prompt(instruction, response, self.holder)}],
                max_tokens=600, json_mode=True))
            if data and "score" in data:
                try:
                    return int(data["score"])
                except Exception:  # noqa: BLE001
                    pass
        return -1
