"""Verify whether a model supports the response prefill feature.

Tests whether the model continues generation from an appended incomplete
assistant message (partial JSON, XML tags, sentence fragments). Models
that extend the prefilled content are classified as supportive.

Usage:
    python scripts/verify_prefill_support.py --provider openrouter \
        --model meta-llama/llama-4-scout --api-key YOUR_KEY
"""

import argparse
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models.model_manager import ModelManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TEST_CASES = [
    {
        "name": "JSON continuation",
        "user": "List three fruits in JSON format.",
        "prefill": '{"fruits": ["apple",',
        "expect_contains": "banana",
    },
    {
        "name": "Sentence fragment",
        "user": "What is the capital of France?",
        "prefill": "The capital of France is",
        "expect_contains": "Paris",
    },
    {
        "name": "XML tag continuation",
        "user": "Describe a cat in XML.",
        "prefill": "<animal><name>",
        "expect_contains": "<",
    },
    {
        "name": "Numbered list",
        "user": "List 5 programming languages.",
        "prefill": "1. Python\n2.",
        "expect_contains": "3.",
    },
]


def verify_model(provider: str, model_name: str, api_key: str) -> dict:
    mm = ModelManager()
    model = mm.create_model(provider, model_name, api_key)

    results = []
    for tc in TEST_CASES:
        messages = [{"role": "user", "content": tc["user"]}]
        messages = model.prepare_messages_with_prefill(messages, tc["prefill"])

        try:
            response = model.call(messages=messages, temperature=0.0)
            continued = (
                not response.startswith("ERROR:")
                and tc["expect_contains"].lower() in response.lower()
            )
            results.append({
                "test": tc["name"],
                "prefill": tc["prefill"],
                "response_snippet": response[:200],
                "continued_from_prefill": continued,
            })
            status = "PASS" if continued else "FAIL"
            logger.info(f"  [{status}] {tc['name']}")
        except Exception as e:
            results.append({
                "test": tc["name"],
                "error": str(e),
                "continued_from_prefill": False,
            })
            logger.info(f"  [ERROR] {tc['name']}: {e}")

    passed = sum(1 for r in results if r["continued_from_prefill"])
    supports_prefill = passed >= len(TEST_CASES) // 2

    summary = {
        "provider": provider,
        "model": model_name,
        "supports_prefill": supports_prefill,
        "tests_passed": f"{passed}/{len(TEST_CASES)}",
        "details": results,
    }

    verdict = "SUPPORTED" if supports_prefill else "NOT SUPPORTED"
    logger.info(f"\nResult: {provider}/{model_name} prefill is {verdict} ({passed}/{len(TEST_CASES)} tests passed)")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Verify prefill support for an LLM")
    parser.add_argument("--provider", required=True, help="Provider name (e.g., openrouter, gemini, deepseek)")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--api-key", required=True, help="API key")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    logger.info(f"Verifying prefill support: {args.provider}/{args.model}")
    result = verify_model(args.provider, args.model, args.api_key)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
