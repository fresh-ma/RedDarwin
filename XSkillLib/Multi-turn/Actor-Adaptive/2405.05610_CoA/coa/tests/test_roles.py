import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from roles import parse_chain  # noqa: E402


class ParseChainTests(unittest.TestCase):
    def test_parses_rounds_array_without_outer_object(self) -> None:
        text = ' rounds: [{"prompt": "first"}, {"prompt": "second"}]'
        self.assertEqual(parse_chain(text, 2), ["first", "second"])

    def test_parses_multiline_round_blocks(self) -> None:
        text = " Round 1:\nfirst prompt\n\nRound 2:\nsecond prompt"
        self.assertEqual(parse_chain(text, 2), ["first prompt", "second prompt"])

    def test_preserves_same_line_round_format(self) -> None:
        text = "Round 1: first prompt\nRound 2: second prompt"
        self.assertEqual(parse_chain(text, 2), ["first prompt", "second prompt"])


if __name__ == "__main__":
    unittest.main()
