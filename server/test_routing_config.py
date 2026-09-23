import json
import tempfile
import unittest
from pathlib import Path

import routing_policy


class RoutingConfigTests(unittest.TestCase):
    def write_config(self, payload):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "routing-config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def capped_config(self):
        return {
            "version": 1,
            "policy_version": "local-capped-v1",
            "routes": [
                {"model": "gpt-5.6-luna", "effort": "low"},
                {"model": "gpt-5.6-sol", "effort": "medium"},
                {"model": "gpt-6-astra", "effort": "ultra"},
                {"model": "deepseek/deepseek-v4-flash-vision-exp", "effort": "low"},
            ],
            "fallback": {"model": "gpt-5.6-sol", "effort": "medium"},
            "off_route": {"model": "gpt-5.6-sol", "effort": "medium"},
            "shadow_route": {"model": "gpt-5.6-sol", "effort": "medium"},
            "codex_dry_enabled": False,
            "sticky_turn_enabled": False,
            "weekly_quota_guard": {
                "enabled": True,
                "remaining_percent_at_or_below": 1,
                "model": "deepseek/deepseek-v4-flash-vision-exp",
                "effort": "low",
            },
        }

    def test_loads_an_explicit_capped_policy(self):
        config = routing_policy.load_policy_config(self.write_config(self.capped_config()))

        self.assertEqual(config["policy_version"], "local-capped-v1")
        self.assertEqual(config["route_pairs"], {
            "deepseek/deepseek-v4-flash-vision-exp:low":
                ("deepseek/deepseek-v4-flash-vision-exp", "low"),
            "gpt-5.6-luna:low": ("gpt-5.6-luna", "low"),
            "gpt-5.6-sol:medium": ("gpt-5.6-sol", "medium"),
            "gpt-6-astra:ultra": ("gpt-6-astra", "ultra"),
        })
        self.assertEqual(config["fallback"], ("gpt-5.6-sol", "medium"))
        self.assertEqual(config["off_route"], ("gpt-5.6-sol", "medium"))
        self.assertEqual(config["shadow_route"], ("gpt-5.6-sol", "medium"))
        self.assertFalse(config["codex_dry_enabled"])
        self.assertFalse(config["sticky_turn_enabled"])
        self.assertEqual(config["weekly_quota_guard"], {
            "enabled": True,
            "remaining_percent_at_or_below": 1,
            "model": "deepseek/deepseek-v4-flash-vision-exp",
            "effort": "low",
        })
        self.assertIn(("gpt-6-astra", "ultra"), config["route_pairs"].values())

    def test_weekly_guard_forces_deepseek_at_or_below_the_configured_threshold(self):
        config = routing_policy.load_policy_config(self.write_config(self.capped_config()))

        self.assertTrue(routing_policy.weekly_guard_active(config, 1.0))
        self.assertTrue(routing_policy.weekly_guard_active(config, 0.0))
        self.assertFalse(routing_policy.weekly_guard_active(config, 1.01))
        self.assertTrue(routing_policy.weekly_guard_active(config, None))

    def test_weekly_guard_model_must_be_an_allowed_route(self):
        payload = self.capped_config()
        payload["weekly_quota_guard"]["model"] = "gpt-5.6-sol"
        payload["weekly_quota_guard"]["effort"] = "medium"

        with self.assertRaisesRegex(ValueError, "weekly quota guard must target a DeepSeek route"):
            routing_policy.load_policy_config(self.write_config(payload))

    def test_rejects_a_fallback_outside_the_allowed_routes(self):
        payload = self.capped_config()
        payload["fallback"] = {"model": "gpt-6-astra", "effort": "medium"}

        with self.assertRaisesRegex(ValueError, "fallback must be one of routes"):
            routing_policy.load_policy_config(self.write_config(payload))

    def test_rejects_duplicate_routes_and_non_boolean_dry_mode(self):
        duplicate = self.capped_config()
        duplicate["routes"].append({"model": "gpt-5.6-luna", "effort": "low"})
        with self.assertRaisesRegex(ValueError, "routes must be unique"):
            routing_policy.load_policy_config(self.write_config(duplicate))

        invalid_dry = self.capped_config()
        invalid_dry["codex_dry_enabled"] = "false"
        with self.assertRaisesRegex(ValueError, "codex_dry_enabled must be a boolean"):
            routing_policy.load_policy_config(self.write_config(invalid_dry))

    def test_rejects_a_non_boolean_sticky_turn_switch(self):
        payload = self.capped_config()
        payload["sticky_turn_enabled"] = "false"

        with self.assertRaisesRegex(ValueError, "sticky_turn_enabled must be a boolean"):
            routing_policy.load_policy_config(self.write_config(payload))


if __name__ == "__main__":
    unittest.main()
