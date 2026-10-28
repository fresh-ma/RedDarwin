"""call_model — call a target/attacker/judge LLM. COPY-REFERENCE (adapt, don't import).

One generic entry point for the most common reproduction need: send chat messages to a model and
get text back. Target spec (string):
  - "fake"           → wiring stub, returns a marker (smoke_only, NEVER evidence)
  - "auto[:<model>]" → **LOCAL-FIRST auto-select** by machine: Mac→Ollama (MLX), GPU→vLLM (or HF
                       transformers), else→OpenRouter. USE THIS for high-call attacks (graph/multi-turn,
                       100-250 calls/goal) — API cost there is unsustainable, local is free.
  - "vllm:<model>"   → LOCAL vLLM OpenAI server on a GPU (`vllm serve <model> --port 8000`). Free/fast
                       on HPC/Docker GPU nodes.
  - "api:<model>"    → OpenAI-compatible endpoint (OpenRouter). **Last-resort fallback** — fine for
                       low-call prompting attacks, NOT for 100+-call graph/multi-turn attacks.
  - "ollama:<model>" → LOCAL Ollama (http://localhost:11434/v1, MLX-accelerated on Apple Silicon,
                       free + fast: gemma4:12b-mlx ~0.7s/call, qwen3-coder:30b). No key, non-reasoning.
                       Good for high-call attacker/judge/helper roles WHEN RUNNING LOCALLY. NOT reachable
                       from HPC compute nodes — use api:<model> there.
  - "local:<hf-id>"  → local HuggingFace chat model (needs a GPU). Use only when OpenRouter lacks it
                       or you need local weights (white-box/fine-tune).

**Target reasoning is OFF by default** (`reasoning=False`): jailbreak eval judges only the FINAL answer,
and a reasoning target (deepseek-v4-flash) balloons ~2s→20-30s per hard call + causes the empty-output
loop. `reasoning=False` sends `extra_body={"reasoning":{"enabled":False}}` (~10× faster). Pass
`reasoning=True` only for attacks that exploit the reasoning trace.

OpenRouter key: `OPENROUTER_API_KEY` is read from the global XSkillForge `.env` —
`load_project_env()` walks up from this file through every ancestor directory and loads any
`.env` it finds (nearest wins; pre-existing shell env always wins). No per-skill `.env`,
no `uv run`, no manual `export`.

Returns (text, status). status="ok" on success, else an honest error tag
(auth_error / rate_limited / provider_block / provider_error / local_import_error / local_error).
"""
from __future__ import annotations

import os
from pathlib import Path

_LOCAL_PIPE_CACHE: dict = {}  # hf_id -> (tokenizer, model); avoids reloading per call


def load_project_env(start: Path | None = None) -> None:
    """Walk up from this file through EVERY ancestor directory and load any `.env` found.

    XSkillLib convention: keys come from the global XSkillForge `.env`; a more local `.env`
    (closer to the skill dir) still wins, and pre-existing shell env always wins. No repo-root
    marker detection — the skill is self-contained and portable wherever it is checked out."""
    here = (start or Path(__file__)).resolve()
    preexisting = set(os.environ)
    # Outermost ancestor first so a nearer `.env` overrides a farther one.
    ancestors = list(here.parents)
    for parent in reversed(ancestors):
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
            if key and value and key not in preexisting:
                os.environ[key] = value


def call_api(messages, model, max_tokens=256, *, reasoning=False,
             base_url="https://openrouter.ai/api/v1", api_key_env="OPENROUTER_API_KEY"):
    try:
        load_project_env()
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=os.environ[api_key_env],
                        timeout=300, max_retries=4)
        # reasoning OFF by default: judge only the final answer; ~10x faster on hard prompts + no
        # empty-output loop. Turn on only for attacks that exploit the reasoning trace.
        # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on, and raise
        # max_tokens so reasoning tokens don't eat the whole completion budget.
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
    """LOCAL Ollama via its OpenAI-compatible endpoint. No key. MLX-accelerated, free, fast.
    First call may be slow (model load into memory); warm calls ~0.7s for gemma4:12b-mlx."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key="ollama",  # key ignored by Ollama
                        timeout=300, max_retries=4)
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens)
        return resp.choices[0].message.content or "", "ok"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"; low = t.lower()
        if "connection" in low or "refused" in low:
            return t + " (is `ollama serve` running?)", "ollama_error"
        return t, "ollama_error"


def call_local(messages, hf_id, max_tokens=256):
    """Local HF chat model; torch/transformers imported lazily; pipe cached per hf_id."""
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
    """LOCAL vLLM OpenAI-compatible server (GPU). Start it: `vllm serve <model> --port 8000`.
    Free + fast on a GPU node (HPC/Docker); use for high-call attacks instead of paying per API call."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key="vllm",  # key ignored by vLLM
                        timeout=300, max_retries=4)
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens)
        return resp.choices[0].message.content or "", "ok"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"
        if "connection" in t.lower() or "refused" in t.lower():
            return t + " (is `vllm serve ... --port 8000` running?)", "vllm_error"
        return t, "vllm_error"


def detect_env() -> str:
    """Return the best LOCAL backend for this machine: 'mac' (Ollama/MLX) / 'gpu' (vLLM/HF) / 'cpu'."""
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


# High-call attacks (graph/multi-turn: 100-250 calls/goal) MUST run on LOCAL models — API cost is
# unsustainable. resolve_auto picks the best FREE local backend for the env, OpenRouter LAST resort.
DEFAULT_LOCAL = {"mac": None, "gpu": None, "cpu": None}


def resolve_auto(model: str = "") -> str:
    """Resolve auto roles to the fixed DeepSeek 0423 API model.

    Local auto-detection is intentionally disabled for experiment fairness.
    """
    return "api:" + (model or "deepseek/deepseek-v4-flash")


def call_model(target, messages, max_tokens=256, *, wiring_check=False):
    """Dispatch on the target spec. Local-first; `api:` (OpenRouter) is the last-resort fallback.
    Specs: fake | auto[:model] | ollama:<model> | vllm:<model> | local:<hf-id> | api:<model>.
    `auto:` self-selects the free local backend for this machine (Mac→Ollama, GPU→vLLM/HF)."""
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
        return call_api(messages, target[4:], max_tokens)
    raise SystemExit("target must be fake | auto[:model] | ollama:<model> | vllm:<model> | "
                     "local:<hf-id> | api:<model>")
