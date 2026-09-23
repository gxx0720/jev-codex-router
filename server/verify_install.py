#!/usr/bin/env python3
"""Read-only Jev Router installation checks; --live opts into one inference."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from jev_paths import codex_router_state_dir


HOME = Path.home()
STATE = Path(codex_router_state_dir())
ROUTER = HOME / ".local/share/codex-router/bin/model-router"
HEALTH_URL = "http://127.0.0.1:4319/health"
MODELS_URL = "http://127.0.0.1:4319/v1/models"
EDGE_URL = "http://127.0.0.1:4202"
# Never send the local caller capability through an HTTP proxy from the user's
# environment. Both health checks and the opt-in live request stay on loopback.
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def command(*args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def get_json(url):
    try:
        with LOCAL_OPENER.open(url, timeout=5) as response:
            if response.status != 200:
                return None
            return json.loads(response.read(65536))
    except (OSError, ValueError, urllib.error.HTTPError):
        return None


def version_at_least(value, minimum):
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        return False
    return tuple(int(part or 0) for part in match.groups()) >= minimum


def typesafe_key_present():
    for path in (HOME / ".hermes/.env", HOME / ".jev.env"):
        try:
            with open(path, encoding="utf-8") as handle:
                if any(line.strip().startswith("TYPESAFE_API_KEY=") and
                       line.split("=", 1)[1].strip().strip('"\' ')
                       for line in handle):
                    return True
        except OSError:
            continue
    return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())


def router_owner_known():
    checkout = ROUTER.parent.parent
    if not (checkout / "src/doctor.mjs").is_file():
        return False
    origin = command("git", "-C", str(checkout), "remote", "get-url", "origin")
    return bool(origin and origin.returncode == 0 and re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"duolahypercho/codex-router(?:\.git)?/?", origin.stdout.strip()))


class Checks:
    def __init__(self):
        self.failed = False

    def add(self, name, passed, next_step):
        print(f"{'OK' if passed else 'FAIL'}  {name}")
        if not passed:
            self.failed = True
            print(f"      Next: {next_step}")


def static_checks(checks):
    checks.add("macOS or Linux", sys.platform == "darwin" or sys.platform.startswith("linux"),
               "Use a supported macOS or Linux host.")
    codex = shutil.which("codex")
    app = sys.platform == "darwin" and any(path.exists() for path in
             (Path("/Applications/Codex.app"), HOME / "Applications/Codex.app"))
    checks.add("Codex CLI or app", bool(codex or app),
               "Install Codex and sign in before continuing.")
    git = command("git", "--version") if shutil.which("git") else None
    checks.add("Git", bool(git and git.returncode == 0), "Install Git.")
    node = command("node", "--version") if shutil.which("node") else None
    checks.add("Node.js >= 22.19", bool(node and node.returncode == 0 and
               version_at_least(node.stdout, (22, 19, 0))), "Install Node.js 22.19+.")
    checks.add("Python >= 3.11", sys.version_info >= (3, 11),
               "Run this checker with Python 3.11+.")
    checks.add("uv or Python venv", bool(shutil.which("uv") or
               (importlib.util.find_spec("venv") and importlib.util.find_spec("ensurepip"))),
               "Install uv or your OS's Python venv package for Codex Router.")
    checks.add("TypeSafe key configured", typesafe_key_present(),
               "Put TYPESAFE_API_KEY in ~/.hermes/.env or ~/.jev.env; do not paste it into chat.")


def router_checks(checks):
    checks.add("Codex Router checkout", ROUTER.is_file(),
               "Install the maintained Codex Router CLI build as described in AGENTS.md.")
    if not ROUTER.is_file():
        return
    known = router_owner_known()
    checks.add("Maintained Codex Router owner", known,
               "Inspect the existing checkout and ask before running or replacing an unknown router.")
    if not known:
        return
    doctor = command(str(ROUTER), "codex", "doctor", timeout=30)
    checks.add("Codex Router doctor", bool(doctor and doctor.returncode == 0),
               "Run the router's codex doctor in your terminal for its detailed diagnosis.")
    providers = read_json(STATE / "generic-providers.json")
    entries = providers.get("providers", []) if isinstance(providers, dict) else []
    jev = next((item for item in entries if isinstance(item, dict) and
                item.get("id") == "jev"), None)
    provider_ok = bool(jev and jev.get("enabled") is True and
                       jev.get("adapter") == "openai-responses" and
                       jev.get("baseUrl", "").rstrip("/") == "http://127.0.0.1:4319/v1")
    checks.add("Jev provider enabled on loopback", provider_ok,
               "Register and enable the jev generic provider via the router CLI.")
    user_models = read_json(STATE / "user-models.json")
    models = user_models.get("models", []) if isinstance(user_models, dict) else []
    curated = any(isinstance(item, dict) and item.get("slug") == "jev/auto" for item in models)
    checks.add("jev/auto curated", curated,
               "Run the router's curate-models jev command and select auto.")
    picker = read_json(STATE / "model-picker.json")
    visible = picker.get("visible", []) if isinstance(picker, dict) else []
    checks.add("jev/auto visible in picker", "jev/auto" in visible,
               "Run the router's refresh-catalog command, then restart Codex.")
    session = command(str(ROUTER), "codex", "chatgpt-session", "status", "--json")
    try:
        status = json.loads(session.stdout) if session and session.returncode == 0 else {}
    except ValueError:
        status = {}
    checks.add("Local ChatGPT sharing usable", status.get("sharing") == "enabled" and
               status.get("session") == "usable",
               "After explicit approval, run codex login and the router's chatgpt-session enable.")


def service_checks(checks):
    health = get_json(HEALTH_URL)
    checks.add("Jev server healthy", isinstance(health, dict) and
               health.get("ok") is True and health.get("service") == "jev-router",
               "Start the server or inspect its service stderr log.")
    models = get_json(MODELS_URL)
    advertised = models.get("data", []) if isinstance(models, dict) else []
    checks.add("Jev endpoint advertises auto", any(isinstance(item, dict) and
               item.get("id") == "auto" for item in advertised),
               "Check the local Jev server on 127.0.0.1:4319.")


def live_check(checks):
    """One small real request; never place the caller secret in argv or output."""
    try:
        secret = (STATE / "caller-secret").read_text(encoding="utf-8").strip()
        if not secret:
            raise ValueError("empty secret")
        url = EDGE_URL + "/_codex-router/" + urllib.parse.quote(secret, safe="") + "/v1/responses"
        body = json.dumps({"model": "jev/auto", "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "Say OK"}]}], "stream": True}).encode()
        request = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
        with LOCAL_OPENER.open(request, timeout=120) as response:
            if response.status != 200:
                raise ValueError("non-200 response")
            created = completed = done = False
            total = 0
            for raw in response:
                total += len(raw)
                if total > 2_000_000:
                    raise ValueError("response too large")
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    done = True
                    break
                event = json.loads(data)
                if not isinstance(event, dict):
                    raise ValueError("invalid SSE event")
                created |= event.get("type") == "response.created"
                completed |= (event.get("type") == "response.completed" and
                              isinstance(event.get("response"), dict) and
                              event["response"].get("status") == "completed")
        passed = created and completed and done
    except (OSError, UnicodeError, ValueError, urllib.error.HTTPError):
        passed = False
    checks.add("End-to-end SSE completed", passed,
               "Check the local caller edge, session authorization, and Jev server logs; no response content was printed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="make one real inference request (may consume quota/credits)")
    args = parser.parse_args(argv)
    checks = Checks()
    static_checks(checks)
    router_checks(checks)
    service_checks(checks)
    if args.live and checks.failed:
        print("SKIP  End-to-end inference (fix the failed checks first)")
    elif args.live:
        live_check(checks)
    else:
        print("SKIP  End-to-end inference (run with --live to test; may consume quota/credits)")
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(main())
