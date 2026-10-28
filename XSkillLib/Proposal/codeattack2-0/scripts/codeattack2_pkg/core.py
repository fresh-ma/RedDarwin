from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROMPT_TYPE = "python_stack_silent"


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def load_template(template_dir: Path) -> str:
    return (template_dir / f"code_{PROMPT_TYPE}.txt").read_text(encoding="utf-8")


def split_goal(goal: str) -> tuple[str, str]:
    """Split the goal into a context fragment and an action fragment.

    Neither fragment alone is a complete harmful commission: for the common
    '<commission> on how to <action>' shape the split lands at 'how to';
    otherwise it falls back to the word midpoint. Applied uniformly to every
    goal (no goal-specific branching).
    """
    goal = goal.strip()
    match = re.search(r"\bhow to\b", goal, re.IGNORECASE)
    if match:
        return goal[: match.start()].strip(), goal[match.start():].strip()
    words = goal.split()
    mid = max(1, len(words) // 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def _encode_stack(var: str, text: str) -> str:
    words = re.split(r"[\s\-]+", text.strip())
    if len(words) == 1:
        words = list(words[0])
    encoded = [word[::-1] for word in words[::-1]]
    return "\n".join(f'    {var}.append("{_quote(word)}")' for word in encoded)


def wrap_goal(goal: str, *, template_dir: Path) -> str:
    """Encode the goal as two fragments in two deques; the full commission
    appears nowhere in the prompt and is never assigned to a single variable
    the victim would echo. decode() recovers each fragment computationally.
    """
    template = load_template(template_dir)
    context, action = split_goal(goal)
    return template.format(
        context_input=_encode_stack("context_stack", context) + "\n",
        action_input=_encode_stack("action_stack", action) + "\n",
    )


def postprocess_response(response: str) -> Any:
    """Extract the payload literal from each output_list.append(...) call —
    with fragment binding, the payload is the LAST string literal in each
    call. Tolerant of a truncated final append (unterminated string)."""
    out = []
    for args in re.findall(r"output_list\.append\((.*?)\)", response, re.DOTALL):
        literals = re.findall(r'"((?:[^"\\]|\\.)*)"', args)
        if literals:
            out.append(literals[-1])
    tail = re.search(r'output_list\.append\((?:(?!\)).)*"((?:[^"\\]|\\.)+)$', response, re.DOTALL)
    if tail and not response.rstrip().endswith(")"):
        out.append(tail.group(1))
    if out:
        return out
    match = re.search(r"output_list\s*=\s*\[\s*(.*?)\s*\]", response, re.DOTALL)
    return match.group(1) if match else response


def normalized_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)
