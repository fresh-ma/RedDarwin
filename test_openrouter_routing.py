import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openrouter_routing import (
    DEEPSEEK_V4_FLASH_0423_PROVIDERS,
    OPENAI_SOL_NON_OPENAI_PROVIDERS,
    provider_route_for_model,
    routed_extra_body,
    routed_json_payload,
)


class ProviderRoutingTests(unittest.TestCase):
    def test_deepseek_0423_keeps_provider_pool(self):
        self.assertEqual(
            provider_route_for_model("api:deepseek/deepseek-v4-flash"),
            {
                "only": list(DEEPSEEK_V4_FLASH_0423_PROVIDERS),
                "allow_fallbacks": True,
            },
        )

    def test_deepseek_0731_uses_cheapest_thirty_percent_pool(self):
        for model in (
            "deepseek/deepseek-v4-flash-0731",
            "api:deepseek/deepseek-v4-flash-0731",
        ):
            with self.subTest(model=model):
                route = provider_route_for_model(model)
                self.assertEqual(set(route["only"]), {
                    "streamlake/fp8", "deepinfra/fp8", "digitalocean",
                    "baseten/fp8", "coreweave/fp8", "cohere",
                    "parasail/fp8", "together",
                })
                self.assertEqual(route["sort"], "price")
                self.assertTrue(route["allow_fallbacks"])
                self.assertEqual(route["max_price"], {
                    "prompt": 0.14, "completion": 0.28,
                })

    def test_deepseek_0731_enforces_caps_for_sdk_and_raw_payloads(self):
        original = {
            "provider": {
                "only": ["relace/fp4", "open-inference/fp4"],
                "sort": "throughput",
                "max_price": {"prompt": 10, "completion": 10},
                "data_collection": "deny",
            },
            "reasoning": {"enabled": False},
        }
        model = "deepseek/deepseek-v4-flash-0731"
        sdk = routed_extra_body(model, original)
        raw = routed_json_payload({"model": model, **original})
        for routed in (sdk, raw):
            self.assertNotIn("relace/fp4", routed["provider"]["only"])
            self.assertNotIn("open-inference/fp4", routed["provider"]["only"])
            self.assertEqual(routed["provider"]["sort"], "price")
            self.assertEqual(routed["provider"]["max_price"], {
                "prompt": 0.14, "completion": 0.28,
            })
            self.assertEqual(routed["provider"]["data_collection"], "deny")
            self.assertEqual(routed["reasoning"], {"enabled": False})
        self.assertEqual(original["provider"]["only"], [
            "relace/fp4", "open-inference/fp4",
        ])
        self.assertEqual(original["provider"]["max_price"]["completion"], 10)

    def test_deepseek_0731_route_mutation_does_not_leak_to_next_call(self):
        model = "deepseek/deepseek-v4-flash-0731"
        route = provider_route_for_model(model)
        route["only"].append("relace/fp4")
        route["max_price"]["completion"] = 10
        fresh = provider_route_for_model(model)
        self.assertNotIn("relace/fp4", fresh["only"])
        self.assertEqual(fresh["max_price"]["completion"], 0.28)

    def test_luna_excludes_openai_providers(self):
        route = provider_route_for_model("openai/gpt-5.6-luna")
        self.assertTrue(route["allow_fallbacks"])
        self.assertNotIn("openai", " ".join(route["only"]).lower())

    def test_sol_excludes_openai_providers(self):
        route = provider_route_for_model("api:openai/gpt-5.6-sol")
        self.assertEqual(
            route,
            {
                "only": list(OPENAI_SOL_NON_OPENAI_PROVIDERS),
                "allow_fallbacks": True,
            },
        )
        self.assertNotIn("openai", " ".join(route["only"]).lower())

    def test_gemini_prefers_vertex_flex_with_same_model_fallback(self):
        self.assertEqual(
            provider_route_for_model("google/gemini-3.8-flash"),
            {
                "order": ["google-vertex/global/flex"],
                "allow_fallbacks": True,
            },
        )
        routed = routed_json_payload({"model": "google/gemini-3.8-flash"})
        self.assertNotIn("only", routed["provider"])

    def test_unrelated_model_is_unchanged(self):
        payload = {"model": "minimax/minimax-m3", "temperature": 0.7}
        self.assertIs(routed_json_payload(payload), payload)

    def test_route_overrides_caller_provider_but_preserves_other_options(self):
        original = {
            "provider": {
                "only": ["openai"],
                "allow_fallbacks": True,
                "data_collection": "deny",
            }
        }
        routed = routed_extra_body("openai/gpt-5.6-sol", original)
        self.assertEqual(
            routed["provider"],
            {
                "only": list(OPENAI_SOL_NON_OPENAI_PROVIDERS),
                "allow_fallbacks": True,
                "data_collection": "deny",
            },
        )
        self.assertEqual(original["provider"]["only"], ["openai"])


if __name__ == "__main__":
    unittest.main()
