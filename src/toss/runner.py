"""Safe foreground process runner used by Toss."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid


MAX_STDERR = 8_192
MAX_SPOOL = 1_000_000
MAX_FINAL = 1_000_000


@dataclass
class TossRunError(RuntimeError):
    runtime: str
    exit_code: int | None
    stderr: str
    partial_output: bool
    spool: Path

    def structured(self) -> dict[str, object]:
        return {"error": "delegate_failed", "runtime": self.runtime, "exit_code": self.exit_code,
                "stderr": self.stderr[:MAX_STDERR], "partial_output": self.partial_output,
                "spool": str(self.spool)}


def state_dir() -> Path:
    root = Path(os.environ.get("TOSS_STATE_DIR", Path.home() / ".local" / "state" / "toss"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _spool(path: Path, output: bytes, complete: bool) -> None:
    # JSON makes recovery explicit and never mistakes partial output for final.
    payload = {"complete": complete, "output": output.decode("utf-8", "replace")[:MAX_SPOOL], "saved_at": time.time()}
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(payload, file)


def recover(path: str | Path) -> dict[str, object]:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def run(
    argv: list[str], prompt: str, *, runtime: str, cwd: str | Path,
    timeout: float = 120.0, env: dict[str, str] | None = None,
    final_path: Path | None = None,
) -> str:
    """Run an argv array without a shell and return only a complete final output."""
    depth = int(os.environ.get("TOSS_DEPTH", "0"))
    if depth >= 1:
        raise TossRunError(runtime, None, "recursion guard: delegate may not invoke toss", False, Path(""))
    spool = state_dir() / f"{uuid.uuid4().hex}.json"
    child_env = os.environ.copy()
    child_env["TOSS_DEPTH"] = str(depth + 1)
    child_env["TOSS_UNAVAILABLE"] = "1"
    if env:
        child_env.update(env)
    process = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(Path(cwd).resolve()), env=child_env, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        partial = expired.output or b""
        if isinstance(partial, str):
            partial = partial.encode()
        try:
            os.killpg(process.pid, signal.SIGTERM)
            remainder, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            remainder, stderr = process.communicate()
        stdout = partial + remainder
        _spool(spool, stdout, False)
        raise TossRunError(runtime, None, "timeout: " + stderr.decode("utf-8", "replace")[:MAX_STDERR], bool(stdout), spool)
    _spool(spool, stdout, process.returncode == 0)
    if process.returncode != 0:
        raise TossRunError(runtime, process.returncode, stderr.decode("utf-8", "replace")[:MAX_STDERR], bool(stdout), spool)
    # Codex writes its final assistant message separately.  Its normal stdout
    # is a transcript/diagnostic stream, so never return it when an extractor
    # artifact was requested.
    if final_path is not None:
        try:
            final = final_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TossRunError(runtime, process.returncode, f"final-message extractor missing: {exc}", bool(stdout), spool)
        finally:
            final_path.unlink(missing_ok=True)
        return final[:MAX_FINAL]
    return stdout.decode("utf-8", "replace")[:MAX_FINAL]
