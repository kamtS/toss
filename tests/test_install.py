"""Black-box checks for the thin host-adapter installer."""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.sh"
NAMES = ("toss-claude", "toss-codex", "toss-tfcode", "toss-recover")


class InstallScriptTests(unittest.TestCase):
    def run_install(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(INSTALL), *args], text=True, capture_output=True, check=False
        )

    def test_install_is_idempotent_and_uses_adapter_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_install("--bin-dir", directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in NAMES:
                link = pathlib.Path(directory) / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (ROOT / "adapters" / name).resolve())

            repeat = self.run_install("--bin-dir", directory)
            self.assertEqual(repeat.returncode, 0, repeat.stderr)
            self.assertIn("Already installed", repeat.stdout)

    def test_diagnose_reports_a_broken_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            link = pathlib.Path(directory) / "toss-codex"
            link.symlink_to(pathlib.Path(directory) / "gone")
            result = self.run_install("--bin-dir", directory, "--diagnose")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BROKEN", result.stderr)

    def test_uninstall_never_removes_a_non_toss_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file = pathlib.Path(directory) / "toss-claude"
            file.write_text("keep me")
            result = self.run_install("--bin-dir", directory, "--uninstall")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(file.exists())
            self.assertEqual(file.read_text(), "keep me")

    def test_adapters_delegate_to_canonical_toss_and_warn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = pathlib.Path(directory) / "toss"
            fake.write_text("#!/bin/sh\nprintf 'delegated:%s\\n' \"$*\"\n")
            fake.chmod(0o755)
            environment = os.environ | {"PATH": f"{directory}:{os.environ['PATH']}"}
            result = subprocess.run(
                [str(ROOT / "adapters" / "toss-codex"), "to", "codex", "hello"],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "delegated:to codex hello\n")
            self.assertIn("untrusted text", result.stderr)


if __name__ == "__main__":
    unittest.main()
