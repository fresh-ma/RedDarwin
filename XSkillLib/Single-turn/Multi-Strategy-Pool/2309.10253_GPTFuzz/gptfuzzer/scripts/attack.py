#!/usr/bin/env python3
"""Paper-local GPTFuzzer (2309.10253) attack runner — fuzz loop + CLI.

Faithful port of sherdencooper/GPTFuzz @ 0c26ccc:
  * seed pool of jailbreak templates (PromptNode tree)
  * MCTSExploreSelectPolicy seed selection (UCT exploit+explore, alpha level
    penalty / beta minimal reward, p-probability non-leaf termination)
  * the five official OpenAI mutators (generate_similar / cross_over / expand /
    shorten / rephrase) with their VERBATIM prompts, driven by an LLM via api:
  * MutateRandomSinglePolicy (random single mutator per call, concatenate=True)
  * per-question target calls + retain-on-jailbreak back into the pool
  * JUDGE = the paper's official finetuned RoBERTa classifier hubert233/GPTFuzz
    (label 1 == jailbroken). A refusal-bypass proxy is reported as a second
    metric only.

Modular layout (each role/piece is its own file so the fuzzer stays readable):
  prompts.py  — verbatim official mutator prompts + QUESTION_PLACEHOLDER / MUTATOR_NAMES
  models.py   — OpenAI-compatible chat client + project .env loader
  roles.py    — target adapter (call_target) + RoBERTa judge + refusal-bypass proxy
  cases.py    — seed/question loaders + message-shaping helpers
  attack.py   — the MCTS fuzz loop (GPTFuzzerRunner) + inspect/render + CLI (this file)

Target / mutator LLM go through any OpenAI-compatible endpoint (OpenRouter by
default). The RoBERTa judge runs locally on CPU via transformers.

Sibling names are re-exported below so ``from attack import X`` keeps working for
any companion script (e.g. a training-corpus generator).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Flat sibling imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# Re-exported (noqa: F401) so companion scripts can do `from attack import ...`.
from prompts import (  # noqa: F401
    MUTATOR_NAMES,
    QUESTION_PLACEHOLDER,
    prompt_cross_over,
    prompt_expand,
    prompt_generate_similar,
    prompt_rephrase,
    prompt_shorten,
)
from models import PAPER_ID, api_chat, load_project_env, project_root  # noqa: F401
from cases import (  # noqa: F401
    DEFAULT_QUESTIONS,
    DEFAULT_SEEDS,
    chat_messages,
    ensure_placeholder,
    load_questions,
    load_seed_templates,
    synthesize_message,
    text_messages,
)
from roles import (  # noqa: F401
    JUDGE_MODEL,
    RoBERTaJudge,
    call_target,
    refusal_bypass,
)

METHOD_ID = "gptfuzzer"


OFFICIAL_REPO = "https://github.com/sherdencooper/GPTFuzz"


OFFICIAL_COMMIT = "0c26cccc3b19cd5eed91d6cb6912431cf2501762"


@dataclass
class PromptNode:
    index: int
    template: str
    parent_index: int | None = None
    mutator: str = "seed"
    level: int = 0
    visits: int = 0
    reward: float = 0.0
    children: list[int] = field(default_factory=list)
    results: list[int] = field(default_factory=list)

    @property
    def jailbreaks(self) -> int:
        return sum(self.results)

    @property
    def rejects(self) -> int:
        return len(self.results) - sum(self.results)


class GPTFuzzerRunner:
    def __init__(
        self,
        templates: list[str],
        questions: list[dict[str, Any]],
        args: argparse.Namespace,
        judge: RoBERTaJudge | None,
    ):
        self.questions = questions
        self.args = args
        self.judge = judge
        self.rng = random.Random(args.seed)
        self.nodes = [PromptNode(index=i, template=t) for i, t in enumerate(templates)]
        self.initial_indices = [n.index for n in self.nodes]
        self.step = 0
        self.results: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.current_query = 0
        self.current_jailbreak = 0
        self.current_reject = 0
        self.last_path: list[int] = []
        self.mutator_calls: list[dict[str, Any]] = []

    # --- MCTSExploreSelectPolicy --------------------------------------- #
    def score(self, node: PromptNode) -> float:
        exploit = node.reward / (node.visits + 1)
        explore = self.args.mcts_ratio * math.sqrt(2 * math.log(max(self.step, 2)) / (node.visits + 0.01))
        return exploit + explore

    def select(self) -> PromptNode:
        self.step += 1
        cur = max((self.nodes[i] for i in self.initial_indices), key=self.score)
        path = [cur.index]
        while cur.children and self.rng.random() >= self.args.mcts_alpha:
            cur = max((self.nodes[i] for i in cur.children), key=self.score)
            path.append(cur.index)
        for idx in path:
            self.nodes[idx].visits += 1
        self.last_path = path
        return cur

    # --- MutateRandomSinglePolicy (LLM mutators) ----------------------- #
    def mutate(self, seed_node: PromptNode) -> tuple[str, str, str | None]:
        mutator = self.rng.choice(MUTATOR_NAMES)
        seed = seed_node.template
        if mutator == "generate_similar":
            instruction = prompt_generate_similar(seed)
        elif mutator == "cross_over":
            other = self.rng.choice(self.nodes).template
            instruction = prompt_cross_over(seed, other)
        elif mutator == "expand":
            instruction = prompt_expand(seed)
        elif mutator == "shorten":
            instruction = prompt_shorten(seed)
        elif mutator == "rephrase":
            instruction = prompt_rephrase(seed)
        else:  # pragma: no cover
            raise AssertionError(mutator)

        if self.args.target == "fake":
            mutated = f"[WIRING_CHECK mutated::{mutator}] {seed}"
            mstatus = "ok"
        else:
            mutated, mstatus = api_chat(
                chat_messages(instruction),
                self.args.mutator_model,
                self.args.base_url,
                self.args.api_key_env,
                self.args.mutator_temperature,
                self.args.mutator_max_tokens,
                self.args.timeout,
            )
        # expand prepends generated sentences to the seed (official behaviour).
        if mstatus == "ok" and mutator == "expand":
            mutated = mutated + seed
        # MutateRandomSinglePolicy(concatentate=True): append parent prompt.
        if mstatus == "ok" and self.args.concatenate:
            mutated = mutated + seed
        self.mutator_calls.append(
            {
                "iteration": self.step,
                "mutator": mutator,
                "status": mstatus,
                "mutator_model": self.args.mutator_model,
                "instruction_preview": instruction[:200],
            }
        )
        if mstatus != "ok":
            return mutator, ensure_placeholder(seed), mstatus
        return mutator, ensure_placeholder(mutated), None

    # --- target evaluation + RoBERTa judge ----------------------------- #
    def evaluate_template(self, node: PromptNode) -> tuple[list[int], list[dict[str, Any]]]:
        # 1) collect target responses for each question
        outputs: list[str] = []
        attempts: list[dict[str, Any]] = []
        for question in self.questions:
            rendered = synthesize_message(question["goal"], node.template)
            if rendered is None:  # invalid template, official treats as no-result
                return [], attempts
            messages = chat_messages(rendered)
            output, status = call_target(messages, self.args)
            outputs.append(output if status == "ok" else "")
            attempts.append(
                {
                    "case_id": len(self.results) + len(attempts) + 1,
                    "iteration": self.step,
                    "prompt_node_index": node.index,
                    "parent_index": node.parent_index,
                    "mutator": node.mutator,
                    "parameters": {
                        "selection": "mcts_explore",
                        "selected_path": list(self.last_path),
                        "mutator": node.mutator,
                        "energy": self.args.energy,
                        "mcts_ratio": self.args.mcts_ratio,
                        "mcts_alpha": self.args.mcts_alpha,
                        "mcts_beta": self.args.mcts_beta,
                    },
                    "sample": {
                        "id": question["id"],
                        "source_row": question["source_row"],
                        "goal_text": question["goal"],
                    },
                    "status": status,
                    "target": self.args.target,
                    "model_input_messages": messages,
                    "model_input_text": text_messages(messages),
                    "model_output_text": output,
                }
            )
            if self.args.request_delay:
                time.sleep(self.args.request_delay)

        # 2) judge the batch with RoBERTa (official predictor); wiring-check skips.
        wiring = getattr(self.args, "wiring_check", False)
        bits: list[int] = []
        if wiring or self.judge is None:
            roberta = [0] * len(outputs)
        else:
            roberta = self.judge.predict(outputs)
        for attempt, output, rb in zip(attempts, outputs, roberta):
            ok = attempt["status"] == "ok"
            jailbroken = bool(ok and rb == 1)
            bit = 1 if jailbroken else 0
            bits.append(bit)
            self.current_query += 1
            self.current_jailbreak += bit
            self.current_reject += 1 - bit
            attempt["judge"] = {
                "name": "wiring_check_shape_only" if wiring else RoBERTaJudge.name,
                "model": JUDGE_MODEL,
                "roberta_class": int(rb),
                "jailbroken": jailbroken,
                "refusal_bypass": bool(ok and refusal_bypass(output)),
            }
        return bits, attempts

    # --- MCTSExploreSelectPolicy.update -------------------------------- #
    def update_rewards(self, evaluated_nodes: list[PromptNode]) -> None:
        if not evaluated_nodes:
            return
        denominator = max(1, len(self.questions) * len(evaluated_nodes))
        succ = sum(n.jailbreaks for n in evaluated_nodes)
        last_level = self.nodes[self.last_path[-1]].level if self.last_path else 0
        for idx in self.last_path:
            reward = (succ / denominator) * max(self.args.mcts_beta, 1 - 0.1 * last_level)
            self.nodes[idx].reward += reward

    def run(self) -> None:
        while not self.should_stop():
            seed_node = self.select()
            evaluated_nodes: list[PromptNode] = []
            retained_indices: list[int] = []
            for _ in range(self.args.energy):
                if self.runtime_budget_exhausted():
                    break
                mutator, template, merr = self.mutate(seed_node)
                candidate = PromptNode(
                    index=len(self.nodes),
                    template=template,
                    parent_index=seed_node.index,
                    mutator=mutator,
                    level=seed_node.level + 1,
                )
                candidate.results, attempts = self.evaluate_template(candidate)
                evaluated_nodes.append(candidate)
                self.results.extend(attempts)
                if candidate.jailbreaks > 0 or self.args.retain_all:
                    self.nodes.append(candidate)
                    self.nodes[seed_node.index].children.append(candidate.index)
                    retained_indices.append(candidate.index)
            self.update_rewards(evaluated_nodes)
            self.trace.append(
                {
                    "iteration": self.step,
                    "selected_node_index": seed_node.index,
                    "selected_path": list(self.last_path),
                    "evaluated": [
                        {
                            "mutator": n.mutator,
                            "level": n.level,
                            "retained": n.index in retained_indices,
                            "results": list(n.results),
                            "template": n.template,
                        }
                        for n in evaluated_nodes
                    ],
                    "pool_size": len(self.nodes),
                    "queries": self.current_query,
                    "successes": self.current_jailbreak,
                }
            )

    def should_stop(self) -> bool:
        if self.args.iterations >= 0 and self.step >= self.args.iterations:
            return True
        return self.runtime_budget_exhausted()

    def runtime_budget_exhausted(self) -> bool:
        if self.args.max_queries >= 0 and self.current_query >= self.args.max_queries:
            return True
        if self.args.max_successes >= 0 and self.current_jailbreak >= self.args.max_successes:
            return True
        return False

    def report(self, seed_source: str, question_source: str, started: float) -> dict[str, Any]:
        ok = [r for r in self.results if r["status"] == "ok"]
        roberta_succ = [r for r in ok if r["judge"].get("jailbroken")]
        bypass_succ = [r for r in ok if r["judge"].get("refusal_bypass")]
        retained = [n for n in self.nodes if n.index not in self.initial_indices]
        best = max(self.nodes, key=lambda n: (n.jailbreaks, n.reward, -n.level))
        used_mutators = sorted({c["mutator"] for c in self.mutator_calls})
        parameter_grid = [
            {"axis": "selection", "value": "mcts_explore"},
            *({"axis": "mutator", "value": name} for name in used_mutators),
        ]
        wiring = bool(getattr(self.args, "wiring_check", False))
        valid_for_completion = bool(
            not wiring
            and self.args.target != "fake"
            and self.judge is not None
            and len(self.results) >= 10
            and len(ok) == len(self.results)
            and len(parameter_grid) >= 2
        )
        return {
            "schema_version": "paper_local_attack_result.v0.2",
            "paper_id": PAPER_ID,
            "method": METHOD_ID,
            "fidelity_level": "paper_algorithm_code",
            "target": self.args.target,
            "mutator_model": self.args.mutator_model,
            "wiring_check": wiring,
            "evidence_level": "wiring_check" if wiring else "real_model_run",
            "run_kind": "model_substitution_run",
            "judge": {
                "name": RoBERTaJudge.name,
                "model": JUDGE_MODEL,
                "kind": "official_finetuned_roberta_classifier",
                "device": "cpu",
                "secondary_metric": "refusal_bypass_proxy",
            },
            "dataset": {"seed_templates": seed_source, "questions": question_source},
            "source_backing": {
                "official_repo": OFFICIAL_REPO,
                "official_commit": OFFICIAL_COMMIT,
                "local_cache": {
                    "seed_templates": DEFAULT_SEEDS,
                    "questions": DEFAULT_QUESTIONS,
                },
            },
            "parameter_grid": parameter_grid,
            "attack_parameters": {
                "selection": "mcts_explore",
                "energy": self.args.energy,
                "iterations": self.args.iterations,
                "max_queries": self.args.max_queries,
                "concatenate": self.args.concatenate,
                "mcts_ratio": self.args.mcts_ratio,
                "mcts_alpha": self.args.mcts_alpha,
                "mcts_beta": self.args.mcts_beta,
                "seed": self.args.seed,
            },
            "summary": {
                "attempts": len(self.results),
                "ok": len(ok),
                "provider_or_runtime_errors": len(self.results) - len(ok),
                "mutator_calls": len(self.mutator_calls),
                "mutator_errors": sum(1 for c in self.mutator_calls if c["status"] != "ok"),
                "mutators_used": used_mutators,
                "roberta_jailbreaks": len(roberta_succ),
                "asr_roberta": len(roberta_succ) / len(ok) if ok else None,
                "refusal_bypass": len(bypass_succ),
                "asr_refusal_bypass": len(bypass_succ) / len(ok) if ok else None,
                "iterations": self.step,
                "seed_pool_size": len(self.nodes),
                "retained_templates": len(retained),
                "seconds": round(time.time() - started, 3),
            },
            "best_template": {
                "prompt_node_index": best.index,
                "parent_index": best.parent_index,
                "mutator": best.mutator,
                "level": best.level,
                "jailbreaks_on_last_eval": best.jailbreaks,
                "template": best.template,
            },
            "seed_pool": [
                {
                    "index": n.index,
                    "parent_index": n.parent_index,
                    "mutator": n.mutator,
                    "level": n.level,
                    "visits": n.visits,
                    "reward": round(n.reward, 6),
                    "children": n.children,
                    "last_results": n.results,
                    "template": n.template,
                }
                for n in self.nodes
            ],
            "mutator_calls": self.mutator_calls,
            "trace": self.trace,
            "results": self.results,
            "valid_for_code_completion": valid_for_completion,
        }


def write_json(data: dict[str, Any], out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def add_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed-templates", default=DEFAULT_SEEDS)
    parser.add_argument("--seed-templates-limit", type=int, default=20)
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS)
    parser.add_argument("--sample-rows", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260609)


def add_fuzz_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--energy", type=int, default=1)
    parser.add_argument("--max-queries", type=int, default=60)
    parser.add_argument("--max-successes", type=int, default=-1)
    parser.add_argument("--retain-all", action="store_true")
    parser.add_argument("--no-concatenate", dest="concatenate", action="store_false")
    parser.add_argument("--mcts-ratio", type=float, default=0.5)
    parser.add_argument("--mcts-alpha", type=float, default=0.1)
    parser.add_argument("--mcts-beta", type=float, default=0.2)


def add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="api:<model>, or fake with --wiring-check")
    parser.add_argument(
        "--mutator-model",
        default="meta-llama/llama-3.3-70b-instruct",
        help="mutator LLM (api model id). NB: OpenRouter openai/* route 403s on jailbreak-template "
        "mutator prompts (provider ToS); the paper used gpt-3.5-turbo, this is a documented substitute.",
    )
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--mutator-temperature", type=float, default=0.0)
    parser.add_argument("--mutator-max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--judge-device", default="cpu", help="device for RoBERTa judge (cpu/cuda)")
    parser.add_argument("--no-judge", action="store_true", help="skip RoBERTa load (wiring-check only)")
    parser.add_argument("--wiring-check", action="store_true", help="allow fake target as shape-only check")


def inspect_command(args: argparse.Namespace) -> dict[str, Any]:
    templates, seed_source = load_seed_templates(args.seed_templates, args.seed_templates_limit, getattr(args, "smoke_only_safe_data", False))
    questions, question_source = load_questions(args.questions, args.sample_rows, args.seed, getattr(args, "smoke_only_safe_data", False))
    return {
        "schema_version": "paper_local_attack_inspect.v0.2",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": "paper_algorithm_code",
        "seed_template_source": seed_source,
        "seed_templates_loaded": len(templates),
        "question_source": question_source,
        "questions_selected": len(questions),
        "question_placeholder": QUESTION_PLACEHOLDER,
        "selection": "mcts_explore",
        "mutators": MUTATOR_NAMES,
        "mutator_kind": "llm_backed_official_prompts",
        "judge": {"name": RoBERTaJudge.name, "model": JUDGE_MODEL},
        "first_seed_preview": templates[0][:240],
    }


def render_command(args: argparse.Namespace) -> dict[str, Any]:
    templates, seed_source = load_seed_templates(args.seed_templates, args.seed_templates_limit, getattr(args, "smoke_only_safe_data", False))
    questions, question_source = load_questions(args.questions, args.sample_rows, args.seed, getattr(args, "smoke_only_safe_data", False))
    items = []
    for idx, question in enumerate(questions):
        template = templates[idx % len(templates)]
        text = synthesize_message(question["goal"], template)
        items.append(
            {
                "case_id": idx + 1,
                "sample": question,
                "seed_template_index": idx % len(templates),
                "template": template,
                "model_input_messages": chat_messages(text),
                "model_input_text": text_messages(chat_messages(text)),
            }
        )
    return {
        "schema_version": "paper_local_attack_render.v0.2",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "seed_template_source": seed_source,
        "question_source": question_source,
        "items": items,
    }


def build_judge(args: argparse.Namespace) -> RoBERTaJudge | None:
    if getattr(args, "wiring_check", False) or getattr(args, "no_judge", False):
        return None
    return RoBERTaJudge(JUDGE_MODEL, device=args.judge_device)


def run_command(args: argparse.Namespace) -> dict[str, Any]:
    if args.target == "fake" and not getattr(args, "wiring_check", False):
        raise SystemExit("--target fake is only allowed with --wiring-check or the smoke command")
    if args.target != "fake" and getattr(args, "wiring_check", False):
        raise SystemExit("--wiring-check is only for --target fake")
    started = time.time()
    templates, seed_source = load_seed_templates(args.seed_templates, args.seed_templates_limit, getattr(args, "smoke_only_safe_data", False))
    questions, question_source = load_questions(args.questions, args.sample_rows, args.seed, getattr(args, "smoke_only_safe_data", False))
    judge = build_judge(args)
    fuzzer = GPTFuzzerRunner(templates, questions, args, judge)
    fuzzer.run()
    return fuzzer.report(seed_source, question_source, started)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-local GPTFuzzer attack runner (official mutators + RoBERTa judge).")
    sub = parser.add_subparsers(dest="mode", required=True)

    smoke = sub.add_parser("smoke")
    smoke.add_argument("--out")

    inspect = sub.add_parser("inspect")
    add_data_args(inspect)
    inspect.add_argument("--out")

    render = sub.add_parser("render")
    add_data_args(render)
    render.add_argument("--out")

    run = sub.add_parser("run")
    add_data_args(run)
    add_fuzz_args(run)
    add_target_args(run)
    run.add_argument("--out")

    args = parser.parse_args()
    if args.mode == "smoke":
        args.seed_templates = None
        args.seed_templates_limit = None
        args.questions = None
        args.sample_rows = 2
        args.seed = 20260609
        args.iterations = 2
        args.energy = 1
        args.max_queries = 4
        args.max_successes = -1
        args.retain_all = False
        args.concatenate = True
        args.mcts_ratio = 0.5
        args.mcts_alpha = 0.1
        args.mcts_beta = 0.2
        args.target = "fake"
        args.mutator_model = "fake"
        args.wiring_check = True
        args.no_judge = True
        args.judge_device = "cpu"
        args.base_url = "https://openrouter.ai/api/v1"
        args.api_key_env = "OPENROUTER_API_KEY"
        args.temperature = 0.0
        args.max_tokens = 64
        args.mutator_temperature = 0.0
        args.mutator_max_tokens = 64
        args.timeout = 60.0
        args.request_delay = 0.0
        args.smoke_only_safe_data = True
        report = run_command(args)
        report["smoke_only"] = True
        write_json(report, args.out)
    elif args.mode == "inspect":
        write_json(inspect_command(args), args.out)
    elif args.mode == "render":
        write_json(render_command(args), args.out)
    else:
        write_json(run_command(args), args.out)


if __name__ == "__main__":
    main()
