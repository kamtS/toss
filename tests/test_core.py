from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile

import unittest
from unittest.mock import patch

from toss.cli import main
from toss.runner import TossRunError, recover, run
from toss.runtimes import TossCapabilityError, command_for, get_runtime, validate_authority


def fake(tmp_path: Path, body: str) -> list[str]:
    program = tmp_path / "fake.py"
    program.write_text("#!/usr/bin/env python3\n" + body)
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return [sys.executable, str(program)]


class CoreTests(unittest.TestCase):
    def test_codex_ro_command_is_explicit(self):
        self.assertEqual(
            command_for(get_runtime("codex"), authority="ro", model=None, variant=None)[:4],
            ["codex", "exec", "--sandbox", "read-only"],
        )

    def test_unenforceable_authority_refuses(self):
        for runtime, authority in [("tfcode", "ro"), ("tfcode", "write"), ("claude", "ro"), ("claude", "write")]:
            with self.assertRaises(TossCapabilityError):
                validate_authority(get_runtime(runtime), authority)


    def test_runner_preserves_stdout_and_uses_stdin(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"TOSS_STATE_DIR": temporary}):
            path = Path(temporary)
            cmd = fake(path, "import sys; print('final:' + sys.stdin.read())")
            self.assertEqual(run(cmd, "hello; $(no-shell)", runtime="fake", cwd=path), "final:hello; $(no-shell)\n")


    def test_failure_is_structured_and_spooled(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"TOSS_STATE_DIR": temporary}):
            path = Path(temporary)
            cmd = fake(path, "import sys; print('partial'); print('bad', file=sys.stderr); raise SystemExit(7)")
            with self.assertRaises(TossRunError) as raised:
                run(cmd, "x", runtime="fake", cwd=path)
            error = raised.exception
            self.assertEqual(error.exit_code, 7)
            self.assertTrue(error.partial_output)
            self.assertEqual(error.stderr, "bad\n")
            self.assertFalse(recover(error.spool)["complete"])


    def test_timeout_kills_and_spool_is_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"TOSS_STATE_DIR": temporary}):
            path = Path(temporary)
            cmd = fake(path, "import time; print('partial', flush=True); time.sleep(10)")
            with self.assertRaises(TossRunError) as raised:
                run(cmd, "x", runtime="fake", cwd=path, timeout=.05)
            self.assertTrue(raised.exception.partial_output)
            self.assertFalse(recover(raised.exception.spool)["complete"])


    def test_recursion_guard(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"TOSS_DEPTH": "1"}):
            with self.assertRaises(TossRunError):
                run(["echo", "no"], "x", runtime="fake", cwd=temporary)


    def test_cli_rejects_tfcode_readonly(self):
        from io import StringIO
        with patch("sys.stderr", StringIO()) as stderr:
            self.assertEqual(main(["to", "tfcode", "--", "hello"]), 2)
            self.assertIn("cannot enforce", stderr.getvalue())

    def test_cli_requires_an_explicit_runtime(self):
        # argparse emits its own usage error; no agent may be selected by default.
        with self.assertRaises(SystemExit) as raised:
            main(["to", "--", "hello"])
        self.assertEqual(raised.exception.code, 2)


    def test_cli_uses_only_final_output(self):
        from io import StringIO
        import toss.cli as cli
        with patch.object(cli, "command_for", lambda *a, **k: ["ignored"]), patch.object(cli, "run", lambda *a, **k: "final only\n"), patch("sys.stdout", StringIO()) as stdout:
            self.assertEqual(main(["to", "codex", "--", "hi"]), 0)
            self.assertEqual(stdout.getvalue(), "final only\n")

    def test_codex_final_message_artifact_wins_over_stdout(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"TOSS_STATE_DIR": temporary}):
            root = Path(temporary)
            artifact = root / "final.txt"
            artifact.write_text("assistant final\n")
            command = fake(root, "print('event stream, not the final message')")
            self.assertEqual(
                run(command, "x", runtime="codex", cwd=root, final_path=artifact),
                "assistant final\n",
            )
            self.assertFalse(artifact.exists())

    def test_cli_requires_explicit_cwd_for_write(self):
        from io import StringIO
        with patch("sys.stderr", StringIO()) as stderr:
            self.assertEqual(main(["to", "codex", "--write", "--", "change it"]), 2)
            self.assertIn("explicit --cwd", stderr.getvalue())

    def test_recover_never_labels_partial_output_final(self):
        with tempfile.TemporaryDirectory() as temporary:
            spool = Path(temporary) / "partial.json"
            spool.write_text(json.dumps({"complete": False, "output": "not done"}))
            self.assertEqual(main(["recover", str(spool)]), 1)
