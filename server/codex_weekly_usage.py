"""Read the signed-in Codex account's weekly usage through app-server RPC."""
import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path


def find_codex_binary():
    candidates = []
    if os.environ.get("CODEX_BIN"):
        configured = os.environ["CODEX_BIN"]
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        candidates.append(Path(configured))
    if os.environ.get("CODEX_INSTALL_DIR"):
        executable = "codex.exe" if os.name == "nt" else "codex"
        candidates.append(Path(os.environ["CODEX_INSTALL_DIR"]) / executable)

    local_app_data = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    if local_app_data:
        local = Path(local_app_data)
        candidates.extend((
            local / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
            local / "Programs" / "Codex" / "resources" / "codex.exe",
        ))
        versioned = local / "OpenAI" / "Codex" / "bin"
        try:
            dirs = sorted(
                (path for path in versioned.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            candidates.extend(path / "codex.exe" for path in dirs)
        except OSError:
            pass

    if os.name == "nt":
        candidates.append(Path.home() / ".local" / "bin" / "codex.exe")
    else:
        candidates.append(Path.home() / ".local" / "bin" / "codex")
    found = next((str(path) for path in candidates if path.is_file()), None)
    return found or shutil.which("codex") or (shutil.which("codex.exe") if os.name == "nt" else None)


def weekly_remaining_percent(rate_limit_response):
    """Return remaining percent for the 7-to-28-day window, or None if absent."""
    if not isinstance(rate_limit_response, dict):
        return None
    by_limit = rate_limit_response.get("rateLimitsByLimitId")
    limits = by_limit.get("codex") if isinstance(by_limit, dict) else None
    if not isinstance(limits, dict):
        limits = rate_limit_response.get("rateLimits")
    if not isinstance(limits, dict):
        return None

    windows = [limits.get(key) for key in ("primary", "secondary")]
    for window in windows:
        if not isinstance(window, dict):
            continue
        duration = window.get("windowDurationMins")
        used = window.get("usedPercent")
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not 7 * 24 * 60 <= duration < 28 * 24 * 60):
            continue
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or not math.isfinite(used)):
            continue
        return max(0.0, min(100.0, 100.0 - float(used)))
    return None


def read_weekly_remaining_percent(timeout=4.0):
    """Fetch fresh account/rateLimits through Codex app-server.

    Returns None on any unavailable or malformed response. The routing policy
    treats None as the protected state when its weekly quota guard is enabled.
    """
    binary = find_codex_binary()
    if not binary:
        return None

    messages = queue.Queue()
    process = None
    reader = None
    deadline = time.monotonic() + max(0.1, float(timeout))
    try:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )

        def read_lines():
            try:
                for line in process.stdout:
                    messages.put(line)
            except Exception as exc:  # surfaced to the request thread
                messages.put(exc)
            finally:
                messages.put(None)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(message):
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def response_for(message_id):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    line = messages.get(timeout=remaining)
                except queue.Empty:
                    return None
                if line is None or isinstance(line, Exception):
                    return None
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(message, dict) and message.get("id") == message_id:
                    return message

        send({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "jev-weekly-quota-guard",
                    "title": "Jev weekly quota guard",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            },
        })
        initialized = response_for(1)
        if not initialized or "error" in initialized:
            return None

        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read", "params": None})
        response = response_for(2)
        if not response or "error" in response:
            return None
        return weekly_remaining_percent(response.get("result"))
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    finally:
        if process is not None:
            try:
                process.stdin.close()
            except (OSError, AttributeError):
                pass
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=0.5)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
