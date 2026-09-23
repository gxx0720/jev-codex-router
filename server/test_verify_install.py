"""The installer verifier must not leak secrets or mistake a partial stream for success."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import verify_install as verify


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter(self.body.splitlines(keepends=True))


class InstallVerification(unittest.TestCase):
    def test_live_check_requires_full_completion_and_never_prints_secrets_or_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "caller-secret").write_text("fixture-private-secret\n", encoding="utf-8")
            good = b"".join(("data: " + json.dumps(event) + "\n\n").encode() for event in (
                {"type": "response.created", "response": {"id": "r"}},
                {"type": "response.output_text.delta", "delta": "private reply"},
                {"type": "response.completed", "response": {"id": "r", "status": "completed"}},
            )) + b"data: [DONE]\n\n"
            with mock.patch.object(verify, "STATE", state):
                for body, expected in ((good, True), (good[:100], False),
                                       (good.replace(b"data: [DONE]\n\n", b""), False)):
                    with self.subTest(expected=expected, length=len(body)):
                        output = io.StringIO()
                        with mock.patch.object(verify.LOCAL_OPENER, "open",
                                               return_value=FakeResponse(body)) as urlopen:
                            with contextlib.redirect_stdout(output):
                                checks = verify.Checks()
                                verify.live_check(checks)
                        self.assertEqual(checks.failed, not expected)
                        self.assertIn("fixture-private-secret", urlopen.call_args.args[0].full_url)
                        self.assertNotIn("fixture-private-secret", output.getvalue())
                        self.assertNotIn("private reply", output.getvalue())

    def test_router_checks_report_missing_route_without_echoing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "generic-providers.json").write_text(json.dumps({"providers": [{
                "id": "jev", "enabled": False, "baseUrl": "private-value",
                "adapter": "openai-responses"}]}), encoding="utf-8")
            router = state / "model-router"
            router.touch()
            output = io.StringIO()
            with mock.patch.object(verify, "STATE", state), mock.patch.object(verify, "ROUTER", router), \
                 mock.patch.object(verify, "router_owner_known", return_value=True), \
                 mock.patch.object(verify, "command", return_value=None), contextlib.redirect_stdout(output):
                checks = verify.Checks()
                verify.router_checks(checks)
            self.assertTrue(checks.failed)
            self.assertIn("FAIL  Jev provider enabled on loopback", output.getvalue())
            self.assertNotIn("private-value", output.getvalue())

    def test_macos_installer_exits_nonzero_if_health_fails(self):
        script = Path(__file__).parent / "install-service.sh"
        for curl_result in ("exit 7\n", "echo '{\"ok\": false}'\n"):
            with self.subTest(curl_result=curl_result), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for name, content in (("launchctl", "exit 0\n"), ("sleep", "exit 0\n"),
                                      ("lsof", "exit 1\n"),
                                      ("curl", curl_result)):
                    path = base / name
                    path.write_text("#!/bin/sh\n" + content, encoding="utf-8")
                    path.chmod(0o755)
                result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                        env={**os.environ, "HOME": tmp,
                                             "PATH": str(base) + os.pathsep + os.environ["PATH"]},
                                        timeout=20, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("failed its health check", result.stderr)
                self.assertNotIn("service OK", result.stdout)

    def test_macos_installer_refuses_an_existing_listener(self):
        script = Path(__file__).parent / "install-service.sh"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name, content in (("launchctl", "exit 0\n"), ("sleep", "exit 0\n"),
                                  ("lsof", "exit 0\n")):
                path = base / name
                path.write_text("#!/bin/sh\n" + content, encoding="utf-8")
                path.chmod(0o755)
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                    env={**os.environ, "HOME": tmp,
                                         "PATH": str(base) + os.pathsep + os.environ["PATH"]},
                                    timeout=20, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Port 4319 is already in use", result.stderr)
            self.assertNotIn("service OK", result.stdout)

    def test_macos_installer_accepts_valid_health(self):
        script = Path(__file__).parent / "install-service.sh"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name, content in (("launchctl", "exit 0\n"), ("sleep", "exit 0\n"),
                                  ("lsof", "exit 1\n"),
                                  ("curl", "echo '{\"ok\": true, \"service\": \"jev-router\"}'\n")):
                path = base / name
                path.write_text("#!/bin/sh\n" + content, encoding="utf-8")
                path.chmod(0o755)
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                    env={**os.environ, "HOME": tmp,
                                         "PATH": str(base) + os.pathsep + os.environ["PATH"]},
                                    timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("service OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
