import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class WorkspaceInitializerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        source = Path(__file__).resolve().parent
        for name in ["scripts/init-redteaming.sh", "openrouter_routing.py", "openrouter_call_ledger.py"]:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
        shutil.copytree(source / "agent_protocols/RedAgent/templates",
                        self.root / "agent_protocols/RedAgent/templates")
        (self.root / "bench").mkdir()
        self.rows = [
            {"query": "  Garden task %d, with a comma\nand a new line. 中文  " % n,
             "category": "planning", "strongreject_source_index": str(100 + n)}
            for n in range(1, 26)
        ]
        with (self.root / "bench/strongreject_50.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.rows[0].keys())
            writer.writeheader()
            writer.writerows(self.rows)
        with (self.root / "bench/advbench_50.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["request", "id"])
            writer.writeheader()
            writer.writerows({"request": "Benign alternate task %d" % n, "id": n} for n in range(1, 6))

    def initialize(self, *arguments, success=True):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            ["bash", str(self.root / "scripts/init-redteaming.sh"), "workspace_001", *arguments],
            cwd=self.root.parent, env=environment, capture_output=True, text=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def load(self, name):
        return json.loads((self.root / "redteaming/workspace_001" / name).read_text())

    def test_selected_csv_rows_preserve_exact_text_and_metadata(self):
        self.initialize("--bench", "Strongreject_50", "--goals", "first-5", "--budget", "10", "--target", "sol")
        run = self.load("RUN.json")
        snapshot = self.load("goals.json")
        self.assertEqual([g["goal"] for g in snapshot["goals"]], [row["query"] for row in self.rows[:5]])
        self.assertEqual([g["source_row"] for g in snapshot["goals"]], [1, 2, 3, 4, 5])
        self.assertEqual(snapshot["goals"][0]["strongreject_source_index"], 101)
        self.assertEqual(run["target"]["model"], "openai/gpt-5.6-sol")
        self.assertIn("only", run["target"]["provider"])
        self.assertTrue(run["locked"])
        self.assertEqual(run["budget"]["victim_calls_per_target"], 50)
        workspace = self.root / "redteaming/workspace_001"
        self.assertEqual(len(list(workspace.glob("goal_*"))), 5)
        self.assertEqual(run["goals_sha256"], hashlib.sha256((workspace / "goals.json").read_bytes()).hexdigest())
        self.assertEqual(snapshot["source_sha256"], hashlib.sha256((self.root / "bench/strongreject_50.csv").read_bytes()).hexdigest())
        for goal in snapshot["goals"]:
            self.assertEqual(self.load(goal["goal_id"] + "/goal.json"), goal)

    def test_original_workspace_only_invocation_keeps_defaults(self):
        self.initialize()
        run = self.load("RUN.json")
        self.assertEqual(run["goal_count"], 20)
        self.assertEqual(run["budget"]["victim_calls_per_target"], 200)
        self.assertIsNone(run["target"]["model"])
        self.assertFalse(run["locked"])

    def test_range_selection_and_another_benchmark(self):
        self.initialize("--bench", "bench/advbench_50.csv", "--goals", "4-5,2", "--budget-per-goal", "2",
                        "--target", "api:example/test-model", "--temperature", "0", "--max-tokens", "512")
        snapshot = self.load("goals.json")
        self.assertEqual([g["source_row"] for g in snapshot["goals"]], [4, 5, 2])
        self.assertEqual([g["goal"] for g in snapshot["goals"]], ["Benign alternate task 4", "Benign alternate task 5", "Benign alternate task 2"])
        run = self.load("RUN.json")
        self.assertEqual(run["budget"]["victim_calls_per_target"], 6)
        self.assertEqual(run["target"]["max_tokens"], 512)
        self.assertEqual(run["target"]["temperature"], 0)
        self.assertEqual(run["target"]["provider"], {})

    def test_all_goals_and_deferred_target(self):
        self.initialize("--bench", "advbench_50.csv", "--goals", "all", "--budget", "3")
        self.assertEqual(self.load("RUN.json")["budget"]["victim_calls_per_target"], 15)
        self.assertIsNone(self.load("RUN.json")["target"]["model"])

    def test_existing_evidence_is_never_overwritten(self):
        self.initialize("--goals", "first-5")
        workspace = self.root / "redteaming/workspace_001"
        (workspace / "goal_001/trail_001.json").write_text('{"victim_calls": 1}')
        before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        self.initialize("--goals", "first-3", "--target", "sol", success=False)
        after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_settings_fail_before_workspace_creation(self):
        for arguments in [("--goals", "first-26"), ("--goals", "0"), ("--goals", "3-1"),
                          ("--goals", "1-2,2"), ("--budget", "0"), ("--temperature", "nan"),
                          ("--max-tokens", "-1"), ("--bench", "../outside.csv"), ("--target", "")]:
            with self.subTest(arguments=arguments):
                self.initialize(*arguments, success=False)
                self.assertFalse((self.root / "redteaming").exists())

    def test_symlink_workspace_is_rejected(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "sentinel").write_text("keep")
        (self.root / "redteaming").mkdir()
        (self.root / "redteaming/workspace_001").symlink_to(outside, target_is_directory=True)
        self.initialize(success=False)
        self.assertEqual((outside / "sentinel").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
