#!/usr/bin/env python3
"""Project translation API CLI.

This is a small, dependency-light wrapper for translation helper work. It
loads credentials from the nearest local .env when present, otherwise the
process environment / outer checkout fallback, and never prints secret values.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists() or ((parent / "data").exists() and (parent / ".codex").exists()):
            return parent
    return Path.cwd()


PROJECT_ROOT = project_root()


def load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


def read_text(args: argparse.Namespace) -> str:
    if getattr(args, "text", None) is not None:
        return args.text
    if getattr(args, "input", None):
        return Path(args.input).read_text(encoding="utf-8", errors="replace")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("provide --text, --input, or stdin")


def configured(provider: str) -> bool:
    if provider == "aws":
        return bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
    if provider == "google":
        return bool(os.environ.get("GOOGLE_TRANSLATE_API_KEY"))
    if provider == "azure":
        return bool(os.environ.get("AZURE_TRANSLATOR_KEY") and os.environ.get("AZURE_TRANSLATOR_REGION"))
    if provider == "deepl":
        return bool(os.environ.get("DEEPL_API_KEY"))
    return False


def resolve_provider(provider: str) -> str:
    if provider != "auto":
        if not configured(provider):
            raise SystemExit(f"{provider} credentials are not configured")
        return provider
    for candidate in ("google", "aws", "azure", "deepl"):
        if configured(candidate):
            return candidate
    raise SystemExit(
        "no translation provider configured; set GOOGLE_TRANSLATE_API_KEY, AWS, "
        "AZURE_TRANSLATOR_KEY/AZURE_TRANSLATOR_REGION, or DEEPL_API_KEY"
    )


def request_json(url: str, payload: Any, headers: dict[str, str]) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"translation API HTTP {exc.code}: {detail}") from exc
    return json.loads(body)


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"translation API HTTP {exc.code}: {detail}") from exc
    return json.loads(body)


def google_url(path: str) -> str:
    key = os.environ["GOOGLE_TRANSLATE_API_KEY"]
    suffix = f"/{path}" if path else ""
    return f"https://translation.googleapis.com/language/translate/v2{suffix}?key={urllib.parse.quote(key)}"


def translate_google(text: str, source: str, target: str, text_format: str, model: str | None) -> str:
    payload: dict[str, Any] = {"q": text, "target": target, "format": text_format}
    if source != "auto":
        payload["source"] = source
    if model:
        payload["model"] = model
    data = request_json(google_url(""), payload, {"Content-Type": "application/json"})
    return html.unescape(data["data"]["translations"][0]["translatedText"])


def detect_google(text: str) -> Any:
    data = request_json(google_url("detect"), {"q": text}, {"Content-Type": "application/json"})
    return data["data"]["detections"][0]


def languages_google(target: str | None) -> Any:
    params = {"key": os.environ["GOOGLE_TRANSLATE_API_KEY"]}
    if target:
        params["target"] = target
    url = "https://translation.googleapis.com/language/translate/v2/languages?" + urllib.parse.urlencode(params)
    return get_json(url)["data"]["languages"]


def translate_azure(text: str, source: str, target: str, text_format: str) -> str:
    key = os.environ["AZURE_TRANSLATOR_KEY"]
    region = os.environ["AZURE_TRANSLATOR_REGION"]
    params = {"api-version": "3.0", "to": target, "textType": "html" if text_format == "html" else "plain"}
    if source != "auto":
        params["from"] = source
    url = "https://api.cognitive.microsofttranslator.com/translate?" + urllib.parse.urlencode(params)
    data = request_json(
        url,
        [{"text": text}],
        {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": key,
            "Ocp-Apim-Subscription-Region": region,
        },
    )
    return data[0]["translations"][0]["text"]


def translate_deepl(text: str, source: str, target: str) -> str:
    key = os.environ["DEEPL_API_KEY"]
    api_host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    # DeepL needs a regional variant for English targets (bare "EN" is rejected);
    # source side accepts bare "EN". Other codes pass through upper-cased.
    target_code = "EN-US" if target.upper() == "EN" else target.upper()
    form: dict[str, str] = {"text": text, "target_lang": target_code}
    if source != "auto":
        form["source_lang"] = source.upper()
    encoded = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        f"https://{api_host}/v2/translate",
        data=encoded,
        headers={
            "Authorization": f"DeepL-Auth-Key {key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"translation API HTTP {exc.code}: {detail}") from exc
    return data["translations"][0]["text"]


def translate_aws(text: str, source: str, target: str) -> str:
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise SystemExit("AWS provider requires boto3: python3 -m pip install boto3") from exc
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    client = boto3.client("translate", region_name=region)
    response = client.translate_text(
        Text=text,
        SourceLanguageCode=source if source != "auto" else "auto",
        TargetLanguageCode=target,
    )
    return response["TranslatedText"]


def translate_text_via_provider(
    provider: str,
    text: str,
    source: str,
    target: str,
    text_format: str = "text",
    model: str | None = None,
) -> tuple[str, str]:
    """Translate text for project callers.

    Returns `(translated_text, resolved_provider)`. This is the stable import
    surface used by paper-local Code that needs the shared translation tool.
    """
    load_project_env()
    resolved = resolve_provider(provider)
    if resolved == "google":
        return translate_google(text, source, target, text_format, model), resolved
    if resolved == "azure":
        return translate_azure(text, source, target, text_format), resolved
    if resolved == "deepl":
        return translate_deepl(text, source, target), resolved
    if resolved == "aws":
        return translate_aws(text, source, target), resolved
    raise AssertionError(resolved)


def do_translate(args: argparse.Namespace) -> int:
    text = read_text(args)
    translated, provider = translate_text_via_provider(
        args.provider,
        text,
        args.source,
        args.target,
        args.format,
        args.model,
    )

    meta = {
        "command": "translate",
        "provider": provider,
        "source": args.source,
        "target": args.target,
        "format": args.format,
        "characters": len(text),
    }
    print(json.dumps(meta, ensure_ascii=False), file=sys.stderr)
    if args.output:
        Path(args.output).write_text(translated, encoding="utf-8")
    else:
        print(translated)
    return 0


def do_detect(args: argparse.Namespace) -> int:
    provider = resolve_provider(args.provider)
    if provider != "google":
        raise SystemExit("detect is currently implemented for --provider google")
    text = read_text(args)
    print(json.dumps({"command": "detect", "provider": provider, "characters": len(text)}, ensure_ascii=False), file=sys.stderr)
    print(json.dumps(detect_google(text), ensure_ascii=False, indent=2))
    return 0


def do_languages(args: argparse.Namespace) -> int:
    provider = resolve_provider(args.provider)
    if provider != "google":
        raise SystemExit("languages is currently implemented for --provider google")
    languages = languages_google(args.target)
    print(json.dumps({"command": "languages", "provider": provider, "count": len(languages)}, ensure_ascii=False), file=sys.stderr)
    print(json.dumps(languages, ensure_ascii=False, indent=2))
    return 0


def do_probe(args: argparse.Namespace) -> int:
    args.text = args.text or "hello world"
    args.input = None
    args.output = None
    args.source = "auto"
    args.format = "text"
    args.model = None
    return do_translate(args)


def do_estimate(args: argparse.Namespace) -> int:
    text = read_text(args)
    chars = len(text)
    meta = {
        "command": "estimate",
        "characters": chars,
        "google_basic_nmt_usd_at_20_per_million": round(chars * 20 / 1_000_000, 6),
        "aws_standard_usd_at_15_per_million": round(chars * 15 / 1_000_000, 6),
    }
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def add_text_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--text")
    parser.add_argument("--input")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate text through configured project APIs.")
    subparsers = parser.add_subparsers(dest="command")

    translate = subparsers.add_parser("translate", help="translate a string, file, or stdin")
    translate.add_argument("--provider", choices=["auto", "google", "aws", "azure", "deepl"], default="auto")
    translate.add_argument("--from", dest="source", default="auto", help="source language code, or auto")
    translate.add_argument("--to", dest="target", required=True, help="target language code")
    translate.add_argument("--format", choices=["text", "html"], default="text")
    translate.add_argument("--model", help="Google Basic model, for example nmt")
    translate.add_argument("--output")
    add_text_args(translate)
    translate.set_defaults(func=do_translate)

    detect = subparsers.add_parser("detect", help="detect source language, currently Google only")
    detect.add_argument("--provider", choices=["google"], default="google")
    add_text_args(detect)
    detect.set_defaults(func=do_detect)

    languages = subparsers.add_parser("languages", help="list supported languages, currently Google only")
    languages.add_argument("--provider", choices=["google"], default="google")
    languages.add_argument("--target", help="localize language names, for example en or zh-CN")
    languages.set_defaults(func=do_languages)

    probe = subparsers.add_parser("probe", help="run a minimal live translation health check")
    probe.add_argument("--provider", choices=["auto", "google", "aws", "azure", "deepl"], default="google")
    probe.add_argument("--to", dest="target", default="zh-CN", help="target language code")
    probe.add_argument("--text")
    probe.set_defaults(func=do_probe)

    estimate = subparsers.add_parser("estimate", help="print character count and rough cost metadata")
    add_text_args(estimate)
    estimate.set_defaults(func=do_estimate)

    return parser


def legacy_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Legacy flat translate command.")
    parser.add_argument("--provider", choices=["auto", "google", "aws", "azure", "deepl"], default="auto")
    parser.add_argument("--from", dest="source", default="auto")
    parser.add_argument("--to", dest="target", required=True)
    parser.add_argument("--text")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--format", choices=["text", "html"], default="text")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    if args.estimate:
        return do_estimate(args)
    if args.probe:
        return do_probe(args)
    return do_translate(args)


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {"translate", "detect", "languages", "probe", "estimate", "-h", "--help"}:
        return legacy_main(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
