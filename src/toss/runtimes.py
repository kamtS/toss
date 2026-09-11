"""Runtime contracts for Toss.

The contracts are intentionally conservative: a runtime is not selected merely
because it is installed; it must be able to enforce the authority requested.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
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
    # TF Code's command surface and JSON event schema are part of the read-only
    # boundary, not merely CLI conveniences.
    "tfcode": Runtime(
        "tfcode", "tfcode", True, False,
        ("glm-5.3", "glm-5.3-flash", "kimi-k3"),
    ),
}


TFCODE_GLM_53 = "toothfairyai/glm-5p3"
TFCODE_GLM_53_FLASH = "toothfairyai/glm-5p3-flash"
TFCODE_KIMI_K3 = "toothfairyai/kimi-k3"
TFCODE_MODEL_ALIASES = {
    "glm-5.3": TFCODE_GLM_53,
    "glm-5p3": TFCODE_GLM_53,
    TFCODE_GLM_53: TFCODE_GLM_53,
    "glm 5.3 flash": TFCODE_GLM_53_FLASH,
    "glm-5.3-flash": TFCODE_GLM_53_FLASH,
    "glm-5p3-flash": TFCODE_GLM_53_FLASH,
    TFCODE_GLM_53_FLASH: TFCODE_GLM_53_FLASH,
    "kimi k3": TFCODE_KIMI_K3,
    "kimi-k3": TFCODE_KIMI_K3,
    "k3": TFCODE_KIMI_K3,
    TFCODE_KIMI_K3: TFCODE_KIMI_K3,
}


TFCODE_REQUIRED_RUN_HELP = ("--agent", "--format", "json", "--model")


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
    if runtime.name == "tfcode" and authority == "write":
        raise TossCapabilityError("tfcode write delegation is refused")
    if authority == "ro" and not runtime.supports_ro:
        raise TossCapabilityError(
            f"{runtime.name} cannot enforce non-interactive read-only authority; refusing"
        )
    if authority == "write" and not runtime.supports_write:
        raise TossCapabilityError(f"{runtime.name} does not support write delegation")


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
        if variant is not None:
            raise TossCapabilityError("tfcode variants are outside the verified read-only contract")
        requested = (model or "glm-5.3").strip().lower()
        try:
            resolved_model = TFCODE_MODEL_ALIASES[requested]
        except KeyError as exc:
            raise TossCapabilityError(
                "tfcode read-only supports only the verified GLM-5.3, "
                "GLM-5.3-Flash, and Kimi-K3 routes"
            ) from exc
        cmd += ["run", "--agent", "build", "--format", "json", "-m", resolved_model]
    return cmd


def verify_runtime(runtime: Runtime, *, env: dict[str, str] | None = None, timeout: float = 3.0) -> str:
    """Resolve the executable and enforce any audited runtime contract."""
    path = executable(runtime)
    if not path:
        raise TossCapabilityError(f"{runtime.name} executable is not installed")
    if runtime.name == "tfcode":
        try:
            help_result = subprocess.run(
                [path, "run", "--help"], capture_output=True, text=True,
                timeout=timeout, check=False, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TossCapabilityError(f"unable to verify tfcode run contract: {exc}") from exc
        help_text = help_result.stdout + "\n" + help_result.stderr
        missing = [token for token in TFCODE_REQUIRED_RUN_HELP if token not in help_text]
        if help_result.returncode != 0 or missing:
            detail = ", ".join(missing) or f"exit {help_result.returncode}"
            raise TossCapabilityError(
                "tfcode does not expose the audited read-only command surface; "
                f"missing: {detail}"
            )
    return path


@contextmanager
def runtime_environment(runtime: Runtime):
    """Yield a complete child environment implementing the runtime contract."""
    if runtime.name != "tfcode":
        yield os.environ.copy()
        return

    # Remove inherited OpenCode controls before installing the audited set.
    # TF_* credentials/profile selection remain available to TF Code itself.
    clean = {
        key: value for key, value in os.environ.items()
        if not key.startswith("OPENCODE_") and key != "TFCODE_WORKER"
    }
    with tempfile.TemporaryDirectory(prefix="toss-tfcode-") as temporary:
        root = Path(temporary)
        config = root / "config"
        home = root / "home"
        managed = root / "managed"
        adapter = root / "adapter"
        for directory in (config, home, managed, adapter):
            directory.mkdir(mode=0o700)
        clean.update({
            "XDG_CONFIG_HOME": str(config),
            "OPENCODE_CONFIG_DIR": str(adapter),
            "OPENCODE_TEST_HOME": str(home),
            "OPENCODE_TEST_MANAGED_CONFIG_DIR": str(managed),
            "OPENCODE_PERMISSION": json.dumps({"*": "deny"}, separators=(",", ":")),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "OPENCODE_AUTO_LOOPS": "0",
            "OPENCODE_AUTO_SHARE": "0",
            "OPENCODE_DISABLE_SHARE": "1",
            "OPENCODE_CONFIG_CONTENT": json.dumps({
                "share": "disabled", "autoshare": False, "formatter": False,
                "plugin": [], "instructions": [], "mcp": {},
                "loops": {"definitions": {}, "auto": []},
            }, separators=(",", ":")),
        })
        yield clean


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
            item["capability_compatible"] = False
            item["read_only_enforced"] = False
        if path:
            try:
                if runtime.name == "tfcode":
                    verified_path = verify_runtime(runtime, timeout=timeout)
                    version = subprocess.run(
                        [verified_path, "--version"], capture_output=True, text=True,
                        timeout=timeout, check=False,
                    )
                    actual = version.stdout.strip()
                    item["version"] = (actual or version.stderr).strip()[:200]
                    item["capability_compatible"] = True
                    item["read_only_enforced"] = runtime.supports_ro
                else:
                    version = subprocess.run(
                        [path, "--version"], capture_output=True, text=True,
                        timeout=timeout, check=False,
                    )
                    item["version"] = (version.stdout or version.stderr).strip()[:200]
            except (OSError, subprocess.TimeoutExpired, TossCapabilityError) as exc:
                item["version"] = "unavailable"
                if runtime.name == "tfcode":
                    item["compatibility_error"] = str(exc)
                    item["capability_compatible"] = False
                    item["read_only_enforced"] = False
        result.append(item)
    return result


def models(runtime_name: str | None = None) -> list[dict[str, str]]:
    selected: Iterable[Runtime] = [get_runtime(runtime_name)] if runtime_name else RUNTIMES.values()
    rows: list[dict[str, str]] = []
    for runtime in selected:
        for model in runtime.known_models:
            rows.append({"runtime": runtime.name, "model": model, "provenance": "known-alias"})
    return rows
