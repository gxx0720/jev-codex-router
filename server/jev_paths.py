"""Shared, platform-aware paths for Jev's Codex Router state."""
import os


def codex_router_state_dir(environ=None, home=None):
    environ = os.environ if environ is None else environ
    codex_home = environ.get("CODEX_HOME")
    if codex_home:
        base = os.path.expanduser(codex_home)
    else:
        base = os.path.join(home or os.path.expanduser("~"), ".codex")
    return os.path.join(base, "codex-router")
