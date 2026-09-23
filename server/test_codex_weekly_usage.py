import io
import json
import subprocess
import unittest
from unittest import mock

import codex_weekly_usage as usage


class WeeklyWindowParsing(unittest.TestCase):
    def test_reads_the_codex_seven_day_window_as_remaining_percent(self):
        response = {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {"usedPercent": 99.2, "windowDurationMins": 10080},
                    "secondary": {"usedPercent": 20, "windowDurationMins": 300},
                },
            },
        }

        self.assertAlmostEqual(usage.weekly_remaining_percent(response), 0.8)

    def test_uses_legacy_codex_rate_limit_shape_when_needed(self):
        self.assertEqual(usage.weekly_remaining_percent({
            "rateLimits": {"primary": {"usedPercent": 95, "windowDurationMins": 10080}},
        }), 5)

    def test_unknown_or_malformed_weekly_usage_stays_unknown(self):
        for response in (
            {},
            {"rateLimits": {"primary": {"usedPercent": 99, "windowDurationMins": 300}}},
            {"rateLimits": {"primary": {"usedPercent": "99", "windowDurationMins": 10080}}},
        ):
            with self.subTest(response=response):
                self.assertIsNone(usage.weekly_remaining_percent(response))


class CodexBinaryDiscovery(unittest.TestCase):
    def test_finds_the_codex_cli_from_path_on_unix_hosts(self):
        env = {"CODEX_BIN": "", "CODEX_INSTALL_DIR": "", "LOCALAPPDATA": ""}
        with mock.patch.dict(usage.os.environ, env, clear=False), \
             mock.patch.object(usage.Path, "is_file", return_value=False), \
             mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/codex" if name == "codex" else None):
            self.assertEqual(usage.find_codex_binary(), "/usr/bin/codex")


class AppServerQuotaRead(unittest.TestCase):
    def test_requests_rate_limits_through_codex_app_server(self):
        init = {"id": 1, "result": {"codexHome": "private"}}
        limits = {"id": 2, "result": {"rateLimits": {
            "primary": {"usedPercent": 98.5, "windowDurationMins": 10080},
        }}}

        class FakeProcess:
            def __init__(self):
                self.stdin = CapturedInput()
                self.stdout = io.StringIO("\n".join(map(json.dumps, [init, limits])) + "\n")
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.terminated = True

        process = FakeProcess()
        with mock.patch.object(usage, "find_codex_binary", return_value="codex.exe"), mock.patch.object(
            usage.subprocess, "Popen", return_value=process
        ):
            self.assertEqual(usage.read_weekly_remaining_percent(timeout=1), 1.5)

        requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(requests[0]["method"], "initialize")
        self.assertEqual(requests[-1]["method"], "account/rateLimits/read")
        self.assertTrue(process.terminated)


class CapturedInput(io.StringIO):
    def __init__(self):
        super().__init__()
        self.saved = ""

    def close(self):
        self.saved = super().getvalue()
        super().close()

    def getvalue(self):
        return self.saved if self.closed else super().getvalue()

    def test_unavailable_codex_binary_returns_unknown(self):
        with mock.patch.object(usage, "find_codex_binary", return_value=None):
            self.assertIsNone(usage.read_weekly_remaining_percent(timeout=0.01))


if __name__ == "__main__":
    unittest.main()
