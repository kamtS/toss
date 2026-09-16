"""Runtime command construction and capability reporting for Toss."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from contextlib import contextmanager
from typing import Iterable


class TossCapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class Runtime:
    name: str
    binary: str
    supports_ro: bool
    supports_write: bool
    known_models: tuple[str, ...] = ()


RUNTIMES: dict[str, Runtime] = {
    "codex": Runtime("codex", "codex", True, True, ("gpt-6-astra", "gpt-5.6-sol")),
    # Claude read-only delegation is deliberately tool-free.  It can review
    # context supplied in the prompt, but cannot inspect or mutate the checkout.
    "claude": Runtime("claude", "claude", True, False, ("sonnet", "opus", "fable")),
    # TF Code authority is expressed through its configured plan/build agents.
    # Plan mode is a runtime policy, not an OS-enforced read-only sandbox.
    "tfcode": Runtime("tfcode", "tfcode", True, True),
}


def get_runtime(name: str) -> Runtime:
    try:
        return RUNTIMES[name]
    except KeyError as exc:
        raise TossCapabilityError(f"unknown runtime: {name}") from exc


def executable(runtime: Runtime) -> str | None:
    return shutil.which(runtime.binary)


def validate_authority(runtime: Runtime, authority: str) -> None:
    if authority not in {"ro", "write"}:
        raise TossCapabilityError(f"unknown authority: {authority}")
    if authority == "ro" and not runtime.supports_ro:
        raise TossCapabilityError(
            f"{runtime.name} cannot enforce non-interactive read-only authority; refusing"
        )
    if authority == "write" and not runtime.supports_write:
        raise TossCapabilityError(f"{runtime.name} does not support write delegation")


def _tfcode_option(name: str, value: str | None) -> str | None:
    """Return a safe ``--name=value`` argv item for a user-selected option."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.startswith("-"):
        raise TossCapabilityError(
            f"tfcode --{name} requires a non-empty value that does not start with '-'"
        )
    return f"--{name}={cleaned}"


def command_for(
    runtime: Runtime, *, authority: str, model: str | None, variant: str | None,
    output_file: Path | None = None, executable_path: str | None = None,
) -> list[str]:
    """Build argv only.  The prompt is always supplied on stdin by runner."""
    validate_authority(runtime, authority)
    cmd = [executable_path or runtime.binary]
    if runtime.name == "codex":
        cmd += ["exec", "--sandbox", "read-only" if authority == "ro" else "workspace-write", "--ephemeral"]
        if model:
            cmd += ["-m", model]
        if output_file:
            cmd += ["--output-last-message", str(output_file)]
        # Codex treats a lone dash as prompt text supplied over stdin.
        cmd.append("-")
    elif runtime.name == "claude":
        cmd += [
            "-p", "--output-format", "text", "--no-session-persistence",
            "--safe-mode", "--tools", "", "--permission-mode", "dontAsk",
        ]
        if model:
            cmd += ["--model", model]
    elif runtime.name == "tfcode":
        model_option = _tfcode_option("model", model)
        variant_option = _tfcode_option("variant", variant)
        cmd += ["run", "--agent", "plan" if authority == "ro" else "build"]
        if authority == "write":
            # Only an explicit --write request opts into TF Code auto-approval.
            cmd.append("--auto")
        cmd += ["--format", "json"]
        if model_option:
            cmd.append(model_option)
        if variant_option:
            cmd.append(variant_option)
    return cmd


def verify_runtime(runtime: Runtime, *, env: dict[str, str] | None = None, timeout: float = 3.0) -> str:
    """Resolve the selected executable without probing a command surface."""
    path = executable(runtime)
    if not path:
        raise TossCapabilityError(f"{runtime.name} executable is not installed")
    return path


@contextmanager
def runtime_environment(runtime: Runtime):
    """Pass the user's runtime configuration and capabilities through unchanged."""
    yield os.environ.copy()


def extract_tfcode_final(stdout: bytes) -> str:
    """Extract only the final assistant message from audited TF Code JSONL."""
    try:
        transcript = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("TF Code output is not valid UTF-8") from exc
    messages: dict[str, list[str]] = {}
    order: list[str] = []
    transcript_session: str | None = None
    allowed = {"text", "tool_use", "step_start", "step_finish", "reasoning", "error"}
    for line_number, line in enumerate(transcript.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON event on line {line_number}") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError(f"invalid JSON event on line {line_number}")
        event_type = event["type"]
        if event_type not in allowed:
            raise ValueError(f"unknown TF Code event {event_type!r}")
        session_id = event.get("sessionID")
        timestamp = event.get("timestamp")
        if not isinstance(session_id, str) or not session_id or not isinstance(timestamp, (int, float)):
            raise ValueError(f"invalid JSON event on line {line_number}")
        if transcript_session is None:
            transcript_session = session_id
        elif session_id != transcript_session:
            raise ValueError("TF Code event stream contains multiple sessions")
        if event_type == "error":
            raise ValueError("TF Code emitted an error event")
        if event_type != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict) or part.get("type") != "text":
            raise ValueError(f"invalid text event on line {line_number}")
        time_data = part.get("time")
        message_id = part.get("messageID")
        text = part.get("text")
        if (
            part.get("sessionID") != session_id
            or not isinstance(time_data, dict) or not time_data.get("end")
            or not isinstance(message_id, str) or not message_id
            or not isinstance(text, str)
        ):
            raise ValueError(f"incomplete text event on line {line_number}")
        if message_id not in messages:
            messages[message_id] = []
            order.append(message_id)
        messages[message_id].append(text)
    if not order:
        raise ValueError("TF Code emitted no completed assistant message")
    final = "".join(messages[order[-1]])
    if not final.strip():
        raise ValueError("TF Code final assistant message is empty")
    return final


def doctor(timeout: float = 3.0) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for runtime in RUNTIMES.values():
        path = executable(runtime)
        item: dict[str, object] = {
            "runtime": runtime.name,
            "installed": bool(path),
            "read_only_enforced": runtime.supports_ro,
            "write_supported": runtime.supports_write,
            "authentication": "not_checked",
            "model_discovery": "static_aliases" if runtime.known_models else "unavailable",
        }
        if runtime.name == "tfcode":
            item["model_discovery"] = "runtime_config"
            item["read_only_enforced"] = False
            item["read_only_mode"] = "runtime_plan_agent"
            item["read_only_auto_approval"] = False
            item["write_mode"] = "runtime_build_agent_with_auto_approval"
        if path:
            try:
                version = subprocess.run(
                    [path, "--version"], capture_output=True, text=True,
                    timeout=timeout, check=False,
                )
                item["version"] = (version.stdout or version.stderr).strip()[:200]
            except (OSError, subprocess.TimeoutExpired, TossCapabilityError) as exc:
                item["version"] = "unavailable"
        result.append(item)
    return result


def models(runtime_name: str | None = None) -> list[dict[str, str]]:
    selected: Iterable[Runtime] = [get_runtime(runtime_name)] if runtime_name else RUNTIMES.values()
    rows: list[dict[str, str]] = []
    for runtime in selected:
        for model in runtime.known_models:
            rows.append({"runtime": runtime.name, "model": model, "provenance": "known-alias"})
    return rows
