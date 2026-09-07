"""Safe foreground process runner used by Toss."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid
from typing import Callable


MAX_STDERR = 8_192
MAX_SPOOL = 1_000_000
MAX_FINAL = 1_000_000
SIGNAL_GRACE = 1.0


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


@dataclass
class TossRecoveryError(RuntimeError):
    spool: Path
    reason: str

    def structured(self) -> dict[str, object]:
        return {"error": "recovery_failed", "spool": str(self.spool), "message": self.reason}


def state_dir() -> Path:
    root = Path(os.environ.get("TOSS_STATE_DIR", Path.home() / ".local" / "state" / "toss"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _spool(path: Path, output: bytes, complete: bool, *, output_bytes: int | None = None) -> None:
    # JSON makes recovery explicit and never mistakes partial output for final.
    total = len(output) if output_bytes is None else output_bytes
    payload = {
        "complete": complete,
        "output": output[:MAX_SPOOL].decode("utf-8", "replace"),
        "output_bytes": total,
        "truncated": total > len(output[:MAX_SPOOL]),
        "saved_at": time.time(),
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(payload, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def recover(path: str | Path) -> dict[str, object]:
    spool = Path(path)
    try:
        with spool.open(encoding="utf-8") as file:
            saved = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TossRecoveryError(spool, str(exc)) from exc
    if not isinstance(saved, dict) or not isinstance(saved.get("complete"), bool) or not isinstance(saved.get("output"), str):
        raise TossRecoveryError(spool, "invalid spool structure")
    return saved


def _drain(
    pipe: object, sink: bytearray, totals: dict[str, int], key: str, limit: int,
    progress: Callable[[bytes, int], None] | None = None,
) -> None:
    total = 0
    read = getattr(pipe, "read1", pipe.read)
    while True:
        # BufferedReader.read(size) may wait to fill the whole request even
        # after the delegate flushes a short partial response. read1() returns
        # currently available pipe data so recovery progresses during a run.
        chunk = read(65_536)
        if not chunk:
            break
        total += len(chunk)
        if len(sink) < limit:
            sink.extend(chunk[:limit - len(sink)])
        if progress is not None:
            progress(bytes(sink), total)
    totals[key] = total


def _feed_stdin(pipe: object, data: bytes) -> None:
    try:
        pipe.write(data)
        pipe.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def run(
    argv: list[str], prompt: str, *, runtime: str, cwd: str | Path,
    timeout: float = 120.0, env: dict[str, str] | None = None,
    final_path: Path | None = None,
    extract_output: Callable[[bytes], str] | None = None,
    replace_env: bool = False,
    on_spool: Callable[[Path], None] | None = None,
) -> str:
    """Run an argv array without a shell and return only a complete final output."""
    depth = int(os.environ.get("TOSS_DEPTH", "0"))
    if depth >= 1:
        raise TossRunError(runtime, None, "recursion guard: delegate may not invoke toss", False, Path(""))
    spool = state_dir() / f"{uuid.uuid4().hex}.json"
    # Establish a recovery locator before launching the delegate.  Until a
    # final response is validated, the spool must remain explicitly partial.
    _spool(spool, b"", False)
    if on_spool is not None:
        on_spool(spool)
    # Security-sensitive adapters can supply a complete environment; ordinary
    # callers retain the convenient overlay behavior.
    child_env = {} if replace_env else os.environ.copy()
    if env:
        child_env.update(env)
    child_env["TOSS_DEPTH"] = str(depth + 1)
    child_env["TOSS_UNAVAILABLE"] = "1"
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(Path(cwd).resolve()), env=child_env, start_new_session=True,
        )
    except OSError as exc:
        raise TossRunError(runtime, None, f"launch failed: {exc}", False, spool) from exc

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    totals = {"stdout": 0, "stderr": 0}
    progress = None if final_path is not None or extract_output is not None else lambda output, total: _spool(
        spool, output, False, output_bytes=total,
    )
    stdout_thread = threading.Thread(target=_drain, args=(process.stdout, stdout_buffer, totals, "stdout", MAX_SPOOL, progress), daemon=True)
    stderr_thread = threading.Thread(target=_drain, args=(process.stderr, stderr_buffer, totals, "stderr", MAX_STDERR), daemon=True)
    assert process.stdin is not None
    stdin_thread = threading.Thread(target=_feed_stdin, args=(process.stdin, prompt.encode("utf-8")), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    stdin_thread.start()

    interrupted: dict[str, int | None] = {"signal": None}
    previous_handlers: dict[int, object] = {}
    kill_timer: threading.Timer | None = None

    def kill_after_grace() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass

    def forward_signal(signum: int, _frame: object) -> None:
        nonlocal kill_timer
        interrupted["signal"] = signum
        try:
            os.killpg(process.pid, signum)
        except OSError:
            return
        if kill_timer is None:
            kill_timer = threading.Timer(SIGNAL_GRACE, kill_after_grace)
            kill_timer.daemon = True
            kill_timer.start()

    # Signal handlers may only be installed in the main thread. Tests and
    # embedders can call Toss elsewhere, where normal process cleanup remains.
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_signal)
    except ValueError:
        previous_handlers.clear()
    timed_out = False
    deadline = time.monotonic() + max(0.0, timeout)

    def terminate_group(signum: int) -> None:
        try:
            os.killpg(process.pid, signum)
        except OSError:
            pass

    try:
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
            # Toss is a foreground operation. A direct child may not leave
            # descendants behind holding pipes or continuing delegated work.
            terminate_group(signal.SIGTERM)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_group(signal.SIGTERM)

        remaining = max(0.0, deadline - time.monotonic())
        stdout_thread.join(remaining)
        remaining = max(0.0, deadline - time.monotonic())
        stderr_thread.join(remaining)
        remaining = max(0.0, deadline - time.monotonic())
        stdin_thread.join(remaining)

        if process.poll() is None or stdout_thread.is_alive() or stderr_thread.is_alive() or stdin_thread.is_alive():
            timed_out = True
            terminate_group(signal.SIGKILL)
            cleanup_deadline = time.monotonic() + .2
            try:
                process.wait(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            stdout_thread.join(max(0.0, cleanup_deadline - time.monotonic()))
            stderr_thread.join(max(0.0, cleanup_deadline - time.monotonic()))
            stdin_thread.join(max(0.0, cleanup_deadline - time.monotonic()))
    finally:
        if kill_timer is not None:
            kill_timer.cancel()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    if process.stdout is not None and not stdout_thread.is_alive():
        process.stdout.close()
    if process.stderr is not None and not stderr_thread.is_alive():
        process.stderr.close()
    stdout = bytes(stdout_buffer)
    stderr = bytes(stderr_buffer)
    # If an escaped descendant kept a pipe open past cleanup, preserve what
    # was observed instead of overwriting the progress spool with zero bytes.
    totals["stdout"] = max(totals["stdout"], len(stdout))
    totals["stderr"] = max(totals["stderr"], len(stderr))
    stdout_truncated = totals["stdout"] > len(stdout)
    stderr_suffix = " [stderr truncated]" if totals["stderr"] > len(stderr) else ""

    saved_output = b"" if final_path is not None or extract_output is not None else stdout
    saved_total = 0 if final_path is not None or extract_output is not None else totals["stdout"]
    if timed_out:
        _spool(spool, saved_output, False, output_bytes=saved_total)
        raise TossRunError(runtime, None, "timeout: " + stderr.decode("utf-8", "replace") + stderr_suffix, bool(saved_total), spool)
    if interrupted["signal"] is not None:
        _spool(spool, saved_output, False, output_bytes=saved_total)
        raise TossRunError(
            runtime, process.returncode, f"interrupted by signal {interrupted['signal']}",
            bool(saved_total), spool,
        )
    if process.returncode != 0:
        _spool(spool, saved_output, False, output_bytes=saved_total)
        raise TossRunError(runtime, process.returncode, stderr.decode("utf-8", "replace") + stderr_suffix, bool(saved_total), spool)
    # Codex writes its final assistant message separately.  Its normal stdout
    # is a transcript/diagnostic stream, so never return it when an extractor
    # artifact was requested.
    if final_path is not None:
        try:
            with final_path.open("rb") as file:
                final_size = os.fstat(file.fileno()).st_size
                final_bytes = file.read(MAX_FINAL + 1)
        except (OSError, UnicodeError) as exc:
            # The event transcript is deliberately never promoted into a
            # recoverable final response when extraction fails.
            raise TossRunError(runtime, process.returncode, f"final-message extractor missing: {exc}", False, spool)
        finally:
            final_path.unlink(missing_ok=True)
        if len(final_bytes) > MAX_FINAL:
            _spool(spool, final_bytes[:MAX_FINAL], False, output_bytes=final_size)
            raise TossRunError(runtime, process.returncode, f"final output exceeds {MAX_FINAL} byte limit", True, spool)
        final = final_bytes.decode("utf-8", "replace")
        _spool(spool, final_bytes, True)
        return final
    if extract_output is not None:
        if stdout_truncated:
            raise TossRunError(runtime, process.returncode, "runtime event stream exceeds spool limit", False, spool)
        try:
            final = extract_output(stdout)
        except (TypeError, ValueError) as exc:
            raise TossRunError(
                runtime, process.returncode, f"final-message extraction failed: {exc}", False, spool,
            ) from exc
        final_bytes = final.encode("utf-8")
        if len(final_bytes) > MAX_FINAL:
            _spool(spool, final_bytes[:MAX_FINAL], False, output_bytes=len(final_bytes))
            raise TossRunError(runtime, process.returncode, f"final output exceeds {MAX_FINAL} byte limit", True, spool)
        _spool(spool, final_bytes, True)
        return final
    if stdout_truncated:
        _spool(spool, stdout, False, output_bytes=totals["stdout"])
        raise TossRunError(runtime, process.returncode, f"final output exceeds {MAX_FINAL} byte limit", True, spool)
    final = stdout.decode("utf-8", "replace")
    _spool(spool, stdout, True)
    return final
