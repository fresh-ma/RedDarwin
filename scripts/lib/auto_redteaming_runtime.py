"""Opt-in transport adapter for auto_redteaming, leaving skill code unchanged.

The private model alias identifies target requests even when the target, helper,
and judge use the same real model. A file lock reserves the one target request
across threads, subprocesses, SDK retries, and wrapper retries.
"""
from __future__ import annotations

import fcntl
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.response
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from openrouter_routing import routed_json_payload


class TargetCallLimitError(RuntimeError):
    pass


class Recorder:
    def __init__(self, config: dict):
        self.config = config
        self.directory = Path(config["directory"])
        self.ledger = self.directory / "calls.jsonl"
        self.is_judge = Path(sys.argv[0]).name == "unified_judge.py"

    def append(self, record: dict, reserve_target=False):
        with (self.directory / ".calls.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if reserve_target and self.ledger.exists():
                prior = [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]
                if any(r["event"] == "request_started" and r["role"] == "target" for r in prior):
                    with self.ledger.open("a") as handle:
                        handle.write(json.dumps({"event": "target_call_blocked", "role": "target"}) + "\n")
                    raise TargetCallLimitError("this skill has already dispatched its one target request")
            with self.ledger.open("a") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def prepare(self, url: str, content: bytes | str):
        # Ignore unrelated HTTP requests and non-JSON bodies.
        if not urlsplit(url).path.rstrip("/").endswith("/chat/completions"):
            return None
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
            return None
        model = payload["model"].removeprefix("api:")
        role = "target" if model == self.config["target_alias"] else "judge" if self.is_judge else "auxiliary"
        if role == "target":
            payload["model"] = self.config["target"]
            for option in ("temperature", "max_tokens"):
                if self.config[option] is not None:
                    payload[option] = self.config[option]
            # Newer clients may use max_completion_tokens instead.
            if self.config["max_tokens"] is not None:
                payload.pop("max_completion_tokens", None)
            url = self.config["base_url"].rstrip("/") + "/chat/completions"
        elif role == "judge" and self.config["judge_model"]:
            payload["model"] = self.config["judge_model"]
        elif role == "auxiliary" and self.config["aux_model"]:
            payload["model"] = self.config["aux_model"]
        # Recompute the exact-model route after resolving aliases or overrides.
        if payload["model"] != model:
            payload.pop("provider", None)
        payload = routed_json_payload(payload)
        call_id = uuid.uuid4().hex
        record = {"event": "request_started", "call_id": call_id, "role": role,
                  "model": payload["model"], "time": time.time()}
        if role == "target":
            record["request"] = payload
        self.append(record, reserve_target=role == "target")
        return url, json.dumps(payload, ensure_ascii=False).encode(), record

    def finish(self, record, status=None, response=None, error=None):
        entry = {"event": "error" if error else "response", "call_id": record["call_id"],
                 "role": record["role"], "model": record["model"], "time": time.time()}
        if error:
            entry["exception_class"] = type(error).__name__
        else:
            entry["http_status"] = status
            if record["role"] == "target":
                entry["response"] = response
        self.append(entry)


def install() -> None:
    config = json.loads(Path(os.environ["REDDARWIN_AUTO_CONFIG"]).read_text())
    recorder = Recorder(config)
    import httpx
    import requests

    original_send = httpx.Client.send
    original_async_send = httpx.AsyncClient.send
    original_requests_send = requests.Session.send
    original_urllib_open = urllib.request.OpenerDirector.open
    original_redirect = urllib.request.HTTPRedirectHandler.redirect_request
    urllib_context = threading.local()

    def changed_httpx(request, prepared):
        url, body, record = prepared
        headers = dict(request.headers)
        headers.pop("content-length", None)
        if record["role"] == "target":
            headers.pop("host", None)
            headers["authorization"] = "Bearer " + os.environ[config["key_env"]]
        extensions = dict(request.extensions)
        if record["role"] == "target" and config.get("request_timeout") is not None:
            extensions["timeout"] = {"connect": 30.0, "read": config["request_timeout"],
                                     "write": 30.0, "pool": 30.0}
        return httpx.Request(request.method, url, headers=headers, content=body,
                             extensions=extensions)

    def send(self, request, **kwargs):
        prepared = recorder.prepare(str(request.url), request.content)
        if prepared is None:
            return original_send(self, request, **kwargs)
        record = prepared[2]
        if record["role"] == "target":
            kwargs["follow_redirects"] = False
        try:
            response = original_send(self, changed_httpx(request, prepared), **kwargs)
            response.read()
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text}
            recorder.finish(record, response.status_code, body)
            return response
        except BaseException as error:
            recorder.finish(record, error=error)
            raise

    async def async_send(self, request, **kwargs):
        await request.aread()
        prepared = recorder.prepare(str(request.url), request.content)
        if prepared is None:
            return await original_async_send(self, request, **kwargs)
        record = prepared[2]
        if record["role"] == "target":
            kwargs["follow_redirects"] = False
        try:
            response = await original_async_send(self, changed_httpx(request, prepared), **kwargs)
            await response.aread()
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text}
            recorder.finish(record, response.status_code, body)
            return response
        except BaseException as error:
            recorder.finish(record, error=error)
            raise

    def requests_send(self, request, **kwargs):
        prepared = recorder.prepare(request.url, request.body)
        if prepared is None:
            return original_requests_send(self, request, **kwargs)
        url, body, record = prepared
        request.url, request.body = url, body
        request.headers["Content-Length"] = str(len(body))
        if record["role"] == "target":
            request.headers["Authorization"] = "Bearer " + os.environ[config["key_env"]]
            kwargs["allow_redirects"] = False
            if config.get("request_timeout") is not None:
                kwargs["timeout"] = config["request_timeout"]
        try:
            response = original_requests_send(self, request, **kwargs)
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text}
            recorder.finish(record, response.status_code, body)
            return response
        except BaseException as error:
            recorder.finish(record, error=error)
            raise

    def redirect(self, request, fp, code, message, headers, new_url):
        if getattr(urllib_context, "target", False):
            return None
        return original_redirect(self, request, fp, code, message, headers, new_url)

    def urllib_open(self, fullurl, data=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT):
        request = fullurl if isinstance(fullurl, urllib.request.Request) else urllib.request.Request(fullurl, data=data)
        prepared = recorder.prepare(request.full_url, data if data is not None else request.data)
        if prepared is None:
            return original_urllib_open(self, fullurl, data, timeout)
        url, body, record = prepared
        headers = {k: v for k, v in request.header_items()
                   if k.lower() not in {"content-length", "host"}}
        if record["role"] == "target":
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
            headers["Authorization"] = "Bearer " + os.environ[config["key_env"]]
            if config.get("request_timeout") is not None:
                timeout = config["request_timeout"]
        changed = urllib.request.Request(url, data=body, headers=headers, method=request.get_method())
        previous = getattr(urllib_context, "target", False)
        urllib_context.target = record["role"] == "target"
        try:
            with original_urllib_open(self, changed, timeout=timeout) as response:
                raw = response.read()
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"text": raw.decode("utf-8", errors="replace")}
                recorder.finish(record, response.status, payload)
                return urllib.response.addinfourl(io.BytesIO(raw), response.headers,
                                                  response.url, response.status)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"text": raw.decode("utf-8", errors="replace")}
            recorder.finish(record, error.code, payload)
            recorder.finish(record, error=error)
            # Preserve the error body for the skill's own error handling.
            raise urllib.error.HTTPError(error.url, error.code, error.msg,
                                         error.headers, io.BytesIO(raw)) from error
        except BaseException as error:
            recorder.finish(record, error=error)
            raise
        finally:
            urllib_context.target = previous

    httpx.Client.send = send
    httpx.AsyncClient.send = async_send
    requests.Session.send = requests_send
    urllib.request.OpenerDirector.open = urllib_open
    urllib.request.HTTPRedirectHandler.redirect_request = redirect
