from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SUPPORTED_PROMPT_TYPES = [
    "python_string",
    "python_string_plus",
    "python_list",
    "python_list_plus",
    "python_stack",
    "python_stack_plus",
    "C_string",
    "go_string",
]


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def load_template(template_dir: Path, prompt_type: str) -> str:
    path = template_dir / f"code_{prompt_type}.txt"
    if not path.exists():
        raise ValueError(f"Unsupported prompt type: {prompt_type}")
    return path.read_text(encoding="utf-8")


def replace_line(template: str, replacement: str, replace_line: int) -> str:
    lines = template.splitlines(keepends=True)
    if replace_line < len(lines):
        lines[replace_line] = replacement
    else:
        lines.append(replacement)
    return "".join(lines)


def wrap_goal(goal: str, *, prompt_type: str, template_dir: Path) -> str:
    template = load_template(template_dir, prompt_type)
    replacement_line = -1
    if "python_stack" in prompt_type:
        words = re.split(r"[\s\-]+", goal)
        if len(words) == 1:
            words = list(words[0])
        wrapped_input = "\n".join(f'    my_stack.append("{_quote(word)}")' for word in words[::-1]) + "\n"
    elif "python_list" in prompt_type:
        wrapped_input = "\n".join(f'    my_list.append("{_quote(word)}")' for word in goal.split()) + "\n"
    elif "python_string" in prompt_type:
        wrapped_input = f'    my_string = "{_quote(goal)}"\n'
    elif "C_string" in prompt_type:
        wrapped_input = f'    std::string my_string = "{_quote(goal)}";\n'
        replacement_line = 10
    elif "go_string" in prompt_type:
        wrapped_input = f'        myQueue := "{_quote(goal)}"\n'
        replacement_line = 17
    else:
        raise ValueError(f"Unsupported prompt type: {prompt_type}")

    if "python" in prompt_type:
        return template.format(wrapped_input=wrapped_input)
    return replace_line(template, wrapped_input, replacement_line)


def postprocess_response(response: str, prompt_type: str) -> Any:
    if "python" in prompt_type:
        parsed = re.findall(r'output_list\.append\("([^"]+)"\)', response)
        if parsed:
            return parsed
        match = re.search(r"output_list\s*=\s*\[\s*(.*?)\s*\]", response, re.DOTALL)
        return match.group(1) if match else response
    if "C" in prompt_type:
        parsed = re.findall(r'outputList\.push_back\("([^"]+)"\);', response)
        return parsed if parsed else response
    if "go" in prompt_type:
        parsed = re.findall(r'outputList\s*=\s*append\(outputList,\s*"([^"]+)"\)', response)
        return parsed if parsed else response
    return response


def normalized_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)

