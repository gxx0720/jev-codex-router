import os
import unittest

from jev_paths import codex_router_state_dir


class CodexRouterStatePath(unittest.TestCase):
    def test_honors_codex_home_override(self):
        self.assertEqual(
            codex_router_state_dir({"CODEX_HOME": "/tmp/codex-profile"}, home="/home/alice"),
            os.path.join(os.path.expanduser("/tmp/codex-profile"), "codex-router"),
        )

    def test_defaults_to_codex_directory_under_user_home(self):
        self.assertEqual(
            codex_router_state_dir({}, home="/home/alice"),
            os.path.join("/home/alice", ".codex", "codex-router"),
        )


if __name__ == "__main__":
    unittest.main()
