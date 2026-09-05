"""Runtime contracts for Toss.

The contracts are intentionally conservative: a runtime is not selected merely
because it is installed; it must be able to enforce the authority requested.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
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
    # TF Code has no proven non-interactive enforced RO mode.  Do not guess.
    "tfcode": Runtime("tfcode", "tfcode", False, False),
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
    if runtime.name == "tfcode" and authority == "write":
        raise TossCapabilityError("tfcode write delegation is refused in v1")
    if authority == "ro" and not runtime.supports_ro:
        raise TossCapabilityError(
            f"{runtime.name} cannot enforce non-interactive read-only authority; refusing"
        )
    if authority == "write" and not runtime.supports_write:
        raise TossCapabilityError(f"{runtime.name} does not support write delegation")


def command_for(
    runtime: Runtime, *, authority: str, model: str | None, variant: str | None,
    output_file: Path | None = None,
) -> list[str]:
    """Build argv only.  The prompt is always supplied on stdin by runner."""
    validate_authority(runtime, authority)
    cmd = [runtime.binary]
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
        cmd += ["run"]
        if model:
            cmd += ["-m", model]
        if variant:
            cmd += ["--variant", variant]
    return cmd


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
        if path:
            try:
                version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=timeout)
                item["version"] = (version.stdout or version.stderr).strip()[:200]
            except (OSError, subprocess.TimeoutExpired):
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
