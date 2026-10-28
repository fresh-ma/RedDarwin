import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from models import successful_chat_result  # noqa: E402


class SuccessfulChatResultTests(unittest.TestCase):
    def test_marks_blank_content_as_empty_response(self) -> None:
        self.assertEqual(successful_chat_result("  \n"), ("", "empty_response"))

    def test_preserves_nonempty_content(self) -> None:
        self.assertEqual(successful_chat_result("answer"), ("answer", "ok"))


if __name__ == "__main__":
    unittest.main()
