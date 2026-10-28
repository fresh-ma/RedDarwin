import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openrouter_call_ledger import (
    finish_failure,
    finish_success,
    new_call,
    prepare_openai_kwargs,
    response_metadata,
)


class CallLedgerTests(unittest.TestCase):
    def test_content_blind_success_and_failure_events(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "calls.jsonl"
            env = {
                "XSF_CALL_LEDGER": str(ledger),
                "XSF_RUN_ID": "smoke",
                "XSF_JOB_ID": "job-1",
                "XSF_ATTACK": "synthetic",
                "XSF_VICTIM": "vendor/victim",
                "XSF_SAMPLE_INDEX": "0",
                "XSF_JOB_ATTEMPT": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                call_id, started = new_call("vendor/victim")
                response = SimpleNamespace(
                    id="gen-safe",
                    model="vendor/victim",
                    provider="SafeProvider",
                    usage=SimpleNamespace(
                        prompt_tokens=2,
                        completion_tokens=1,
                        total_tokens=3,
                        model_extra={"cost": 0.01},
                    ),
                    model_extra={
                        "openrouter_metadata": {
                            "attempt": 2,
                            "attempts": [
                                {"provider": "A", "model": "vendor/victim", "status": 500},
                                {"provider": "B", "model": "vendor/victim", "status": 200},
                            ],
                            "unsafe_extra": "must-not-be-written",
                        }
                    },
                )
                finish_success("vendor/victim", call_id, started, response)
                other_id, other_started = new_call("vendor/helper")
                finish_failure("vendor/helper", other_id, other_started, ValueError("secret"))

            text = ledger.read_text()
            self.assertNotIn("must-not-be-written", text)
            self.assertNotIn("secret", text)
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertEqual([row["role"] for row in rows], ["victim", "victim", "other", "other"])
            self.assertEqual(rows[1]["router_attempt"], 2)
            self.assertEqual(rows[1]["cost"], 0.01)
            self.assertEqual(rows[3]["exception_class"], "ValueError")

    def test_tracking_headers_and_pseudonymous_user(self):
        with patch.dict(os.environ, {"XSF_RUN_ID": "r", "XSF_JOB_ID": "j"}, clear=False):
            kwargs = {}
            prepare_openai_kwargs(kwargs)
            self.assertEqual(kwargs["extra_headers"]["X-OpenRouter-Metadata"], "enabled")
            self.assertRegex(kwargs["user"], r"^xsf_[0-9a-f]{24}$")


if __name__ == "__main__":
    unittest.main()
