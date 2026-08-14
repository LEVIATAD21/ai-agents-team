"""Testes locais para as guardas de segurança do NEXUS."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nexus


class SecurityPolicyTests(unittest.TestCase):
    def test_workspace_path_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, error = nexus.workspace_path("notes/result.txt", root)
            self.assertIsNone(error)
            self.assertEqual(path, root / "notes" / "result.txt")

    def test_workspace_path_blocks_traversal_and_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, error = nexus.workspace_path("../outside.txt", root)
            self.assertIsNone(path)
            self.assertIn("escapes", error)
            path, error = nexus.workspace_path(".env", root)
            self.assertIsNone(path)
            self.assertIn("environment", error)

    def test_safe_command_allowlist(self):
        args, error = nexus.safe_command_args("git status --short")
        self.assertIsNone(error)
        self.assertEqual(args, ["git", "status", "--short"])

    def test_safe_command_blocks_shell_and_destructive_tokens(self):
        args, error = nexus.safe_command_args("git status | cat")
        self.assertIsNone(args)
        self.assertIn("shell", error)
        args, error = nexus.safe_command_args("rm -rf demo")
        self.assertIsNone(args)
        self.assertIn("high-impact", error)

    def test_url_policy_rejects_local_destinations(self):
        url, error = nexus.allowed_web_url("https://example.com/docs")
        self.assertEqual(url, "https://example.com/docs")
        self.assertIsNone(error)
        url, error = nexus.allowed_web_url("http://127.0.0.1:3000")
        self.assertIsNone(url)
        self.assertIn("local-network", error)


if __name__ == "__main__":
    unittest.main()
