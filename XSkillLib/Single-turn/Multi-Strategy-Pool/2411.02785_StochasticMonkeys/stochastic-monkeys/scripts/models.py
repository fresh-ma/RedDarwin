"""models.py — model client + walk-up .env loader for Stochastic Monkeys.

Copied from code_knowledge/snippets/functions/call_model.py (project rule = self-contained, no shared
import). Every role (target / judge) dispatches through `call_model(spec, messages, max_tokens)`.

Specs: fake | auto[:model] | ollama:<model> | vllm:<model> | local:<hf-id> | api:<model>.
Target reasoning is OFF by default — jailbreak eval judges the FINAL answer only (~10x faster).
"""
from __future__ import annotations

import os
from pathlib import Path

_LOCAL_PIPE_CACHE: dict = {}


def load_project_env(start: Path | None = None) -> None:
    """Walk up from this file through EVERY ancestor directory, loading each `.env`
    found (nearest wins; pre-existing env vars are never overridden). This finds the
    global XSkillForge/.env above XSkillLib — no per-skill .env, no manual export."""
    here = (start or Path(__file__)).resolve()
    preexisting = set(os.environ)
    for parent in (here.parent, *here.parents):
        env_path = parent / ".env"
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in os.environ and key not in preexisting:
                os.environ[key] = value


def call_api(messages, model, max_tokens=256, *, reasoning=False,
             base_url="https://openrouter.ai/api/v1", api_key_env="OPENROUTER_API_KEY"):
    try:
        load_project_env()
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=os.environ[api_key_env])
        # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on, and
        # raise max_tokens so reasoning tokens don't eat the whole completion budget.
        gpt_oss = "gpt-oss" in model.lower()
        if gpt_oss and max_tokens < 1024:
            max_tokens = 1024
        extra = None if (reasoning or gpt_oss) else {"reasoning": {"enabled": False}}
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens, extra_body=extra)
        return resp.choices[0].message.content or "", "ok"
    except KeyError:
        return f"{api_key_env} is required for api targets", "auth_error"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"; low = t.lower()
        if "429" in low or "rate limit" in low:
            return t, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return t, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return t, "provider_block"
        return t, "provider_error"


def call_ollama(messages, model, max_tokens=256, *, base_url="http://localhost:11434/v1"):
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key="ollama")
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens)
        return resp.choices[0].message.content or "", "ok"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"; low = t.lower()
        if "connection" in low or "refused" in low:
            return t + " (is `ollama serve` running?)", "ollama_error"
        return t, "ollama_error"


def call_local(messages, hf_id, max_tokens=256):
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:  # noqa: BLE001
        return f"local target needs torch+transformers: {type(exc).__name__}: {exc}", "local_import_error"
    try:
        if hf_id not in _LOCAL_PIPE_CACHE:
            tok = AutoTokenizer.from_pretrained(hf_id)
            mdl = AutoModelForCausalLM.from_pretrained(hf_id, torch_dtype="auto", device_map="auto")
            _LOCAL_PIPE_CACHE[hf_id] = (tok, mdl)
        tok, mdl = _LOCAL_PIPE_CACHE[hf_id]
        ids = tok.apply_chat_template(messages, add_generation_prompt=True,
                                      return_tensors="pt", tokenize=True).to(mdl.device)
        gen = mdl.generate(ids, max_new_tokens=max_tokens, do_sample=False)
        return tok.decode(gen[0][ids.shape[-1]:], skip_special_tokens=True), "ok"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}", "local_error"


def call_vllm(messages, model, max_tokens=256, *, base_url="http://localhost:8000/v1"):
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key="vllm")
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens)
        return resp.choices[0].message.content or "", "ok"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"
        if "connection" in t.lower() or "refused" in t.lower():
            return t + " (is `vllm serve ... --port 8000` running?)", "vllm_error"
        return t, "vllm_error"


def detect_env() -> str:
    import platform, shutil, subprocess
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mac"
    if shutil.which("nvidia-smi"):
        try:
            if subprocess.run(["nvidia-smi"], capture_output=True, timeout=5).returncode == 0:
                return "gpu"
        except Exception:  # noqa: BLE001
            pass
    return "cpu"


def _port_live(host_port: str) -> bool:
    import socket
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host or "localhost", int(port or 80)), timeout=1.0):
            return True
    except Exception:  # noqa: BLE001
        return False


DEFAULT_LOCAL = {"mac": None, "gpu": None, "cpu": None}


def resolve_auto(model: str = "") -> str:
    """Resolve auto roles to the fixed DeepSeek 0423 API model.

    Local auto-detection is intentionally disabled for experiment fairness.
    """
    return "api:" + (model or "deepseek/deepseek-v4-flash")


def call_model(target, messages, max_tokens=256, *, reasoning=False, wiring_check=False):
    if target == "fake":
        if not wiring_check:
            raise SystemExit("target 'fake' is only for --wiring-check / smoke (never evidence)")
        return "WIRING_CHECK_FAKE_OUTPUT", "smoke_only"
    if target == "auto" or target.startswith("auto:"):
        target = resolve_auto(target[5:] if ":" in target else "")
    if target.startswith("ollama:"):
        return call_ollama(messages, target[7:], max_tokens)
    if target.startswith("vllm:"):
        return call_vllm(messages, target[5:], max_tokens)
    if target.startswith("local:"):
        return call_local(messages, target[6:], max_tokens)
    if target.startswith("api:"):
        return call_api(messages, target[4:], max_tokens, reasoning=reasoning)
    raise SystemExit("target must be fake | auto[:model] | ollama:<model> | vllm:<model> | "
                     "local:<hf-id> | api:<model>")
