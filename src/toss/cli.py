"""The small, deliberately conservative Toss command-line interface."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

from .runner import TossRecoveryError, TossRunError, recover, run, state_dir
from .runtimes import (
    TossCapabilityError, command_for, doctor, extract_tfcode_final, get_runtime,
    models, runtime_environment, validate_authority, verify_runtime,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toss")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p_models = commands.add_parser("models")
    p_models.add_argument("runtime", choices=["codex", "claude", "tfcode"], nargs="?")
    def delegation(name: str, *, default_authority: str) -> argparse.ArgumentParser:
        item = commands.add_parser(name)
        # A delegation must name its destination. This prevents surprise model
        # execution and leaves every hand-off visible in shell history.
        item.add_argument("runtime", choices=["codex", "claude", "tfcode"])
        item.add_argument("--model")
        item.add_argument("--variant")
        authority = item.add_mutually_exclusive_group()
        authority.add_argument("--ro", action="store_const", const="ro", dest="authority")
        authority.add_argument("--write", action="store_const", const="write", dest="authority")
        item.set_defaults(authority=default_authority)
        item.add_argument("--cwd", type=Path)
        item.add_argument("--timeout", type=float, default=120.0)
        return item
    delegation("to", default_authority="write")
    review = delegation("review", default_authority="ro")
    review.add_argument("--base", default="HEAD")
    review.add_argument("--scope", choices=["auto", "working-tree", "branch"], default="auto")
    recover_parser = commands.add_parser("recover")
    recover_parser.add_argument("spool", type=Path)
    return parser


MAX_UNTRACKED_FILE_BYTES = 200_000
MAX_REVIEW_CHUNK_BYTES = 500_000


def _git(cwd: Path, args: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
            cwd=cwd, capture_output=True, text=text, env=env,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TossCapabilityError(f"git inspection failed: {exc}") from exc


def _require_git(cwd: Path, args: list[str], description: str, *, text: bool = True) -> subprocess.CompletedProcess:
    result = _git(cwd, args, text=text)
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
        raise TossCapabilityError(f"{description}: {stderr.strip() or 'git exited ' + str(result.returncode)}")
    return result


def _resolve_base(cwd: Path, base: str) -> str:
    # Resolve user input to an object ID before using it in another Git argv.
    # --end-of-options makes refs such as --output=/tmp/x inert input, and a
    # commit peel prevents blobs and trees from masquerading as review bases.
    result = _require_git(
        cwd, ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{base}^{{commit}}"],
        f"invalid review base {base!r}",
    )
    resolved = result.stdout.strip()
    if not resolved:
        raise TossCapabilityError(f"invalid review base {base!r}")
    return resolved


def _untracked_context(cwd: Path) -> str:
    result = _require_git(cwd, ["ls-files", "--others", "--exclude-standard", "-z"], "unable to list untracked files", text=False)
    chunks: list[str] = []
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        name = raw_name.decode("utf-8", "surrogateescape")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            chunks.append(f"\n[untracked omitted: {name} (unsafe path)]\n")
            continue
        path = cwd / name
        try:
            # Never follow an untracked symlink outside the checkout, and keep
            # prompt growth bounded. Binary/large files remain identified.
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode):
                    chunks.append(f"\n[untracked omitted: {name} (not a regular file)]\n")
                    continue
                if info.st_size > MAX_UNTRACKED_FILE_BYTES:
                    chunks.append(f"\n[untracked omitted: {name} ({info.st_size} bytes)]\n")
                    continue
                data = file.read(MAX_UNTRACKED_FILE_BYTES + 1)
                if len(data) > MAX_UNTRACKED_FILE_BYTES:
                    chunks.append(f"\n[untracked omitted: {name} (grew while reading)]\n")
                    continue
        except OSError as exc:
            chunks.append(f"\n[untracked omitted: {name} ({exc})]\n")
            continue
        if b"\0" in data:
            chunks.append(f"\n[untracked binary: {name} ({len(data)} bytes)]\n")
            continue
        chunks.append(f"\n--- /dev/null\n+++ b/{name}\n" + data.decode("utf-8", "replace"))
    return "".join(chunks)


def _review_prompt(args: argparse.Namespace) -> tuple[str, str]:
    root_result = _require_git(args.cwd, ["rev-parse", "--show-toplevel"], "--cwd is not a Git checkout")
    root = Path(root_result.stdout.strip()).resolve()
    base = _resolve_base(root, args.base)
    status = _require_git(root, ["status", "--porcelain=v1", "-z"], "unable to inspect working tree", text=False)
    resolved_scope = args.scope
    if resolved_scope == "auto":
        resolved_scope = "working-tree" if status.stdout else "branch"
    if resolved_scope == "working-tree":
        diff = _require_git(root, ["diff", "--no-ext-diff", "--no-textconv", "--binary", base, "--"], "unable to build working-tree review diff").stdout
        diff += _untracked_context(root)
    else:
        merge_base = _require_git(root, ["merge-base", base, "HEAD"], "review base and HEAD have no merge base").stdout.strip()
        diff = _require_git(root, ["diff", "--no-ext-diff", "--no-textconv", "--binary", merge_base, "HEAD", "--"], "unable to build branch review diff").stdout
    if not diff.strip():
        raise TossCapabilityError(
            f"review scope {resolved_scope!r} has no changes; choose a meaningful --base or working tree"
        )
    return "Review this change. Identify concrete risks and suggested fixes.\n\n" + diff, resolved_scope


def _review_chunks(prompt: str) -> list[str]:
    """Keep all review text while bounding each delegate's input size."""
    if len(prompt.encode("utf-8")) <= MAX_REVIEW_CHUNK_BYTES:
        return [prompt]
    # Leave space for the label, even for a change with many chunks.
    body_limit = MAX_REVIEW_CHUNK_BYTES - 1_024
    pieces: list[tuple[str, str | None, str | None]] = []
    current: list[str] = []
    current_bytes = 0
    current_file: str | None = None
    current_hunk: str | None = None
    piece_file: str | None = None
    piece_hunk: str | None = None

    def flush() -> None:
        nonlocal current, current_bytes
        pieces.append(("".join(current), piece_file, piece_hunk))
        current, current_bytes = [], 0

    for line in prompt.splitlines(keepends=True):
        if line.startswith("diff --git "):
            current_file, current_hunk = line.rstrip("\n"), None
        elif line.startswith("@@ "):
            current_hunk = line.rstrip("\n")
        elif line.startswith("+++ b/"):
            current_file = line.rstrip("\n")
        encoded = line.encode("utf-8")
        while encoded:
            remaining = body_limit - current_bytes
            if remaining == 0:
                flush()
                remaining = body_limit
            if len(encoded) <= remaining:
                if not current:
                    piece_file, piece_hunk = current_file, current_hunk
                current.append(encoded.decode("utf-8"))
                current_bytes += len(encoded)
                break
            # Prefer a line boundary, but a single very long line must also
            # be included in full. Never split a UTF-8 code point.
            if current:
                flush()
                continue
            boundary = body_limit
            while boundary and boundary < len(encoded) and encoded[boundary] & 0xC0 == 0x80:
                boundary -= 1
            if not boundary:
                raise TossCapabilityError("review chunk limit cannot fit one character")
            piece_file, piece_hunk = current_file, current_hunk
            current.append(encoded[:boundary].decode("utf-8"))
            current_bytes = boundary
            encoded = encoded[boundary:]
    if current:
        flush()
    total = len(pieces)
    return [
        f"Review chunk {index}/{total} of one change. This is partial context; "
        "identify concrete risks in the supplied text and do not claim to have reviewed other chunks.\n"
        + (f"File context: {file[:120]}\n" if file else "")
        + (f"Hunk context: {hunk[:80]}\n" if hunk else "")
        + "\n"
        + piece
        for index, (piece, file, hunk) in enumerate(pieces, 1)
    ]


def _format_review_outputs(outputs: list[str], total: int) -> str:
    return "".join(
        f"## Review chunk {index}/{total}\n<TOSS_DELEGATE_OUTPUT untrusted=\"true\">\n"
        f"{output}\n</TOSS_DELEGATE_OUTPUT>\n"
        for index, output in enumerate(outputs, 1)
    )


def _prompt(args: argparse.Namespace) -> str:
    text = args.prompt
    if text and text[0] == "--":
        text = text[1:]
    if not text:
        raise TossCapabilityError("a prompt is required after --")
    return " ".join(text)


def main(argv: list[str] | None = None) -> int:
    # Keep the prompt behind `--` without letting argparse's REMAINDER swallow
    # legitimate flags placed after the runtime (`toss to codex --ro -- ...`).
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw:
        marker = raw.index("--")
        parsed, prompt = raw[:marker], raw[marker + 1 :]
    else:
        parsed, prompt = raw, []
    args = _parser().parse_args(parsed)
    args.prompt = prompt
    if args.command == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    if args.command == "models":
        print(json.dumps(models(args.runtime), indent=2))
        return 0
    if args.command == "recover":
        try:
            saved = recover(args.spool)
            if not saved["complete"]:
                print(json.dumps({"error": "partial_spool", "spool": str(args.spool)}), file=sys.stderr)
                return 1
            sys.stdout.write(saved["output"])
            return 0
        except TossRecoveryError as exc:
            print(json.dumps(exc.structured()), file=sys.stderr)
            return 1
    try:
        runtime = get_runtime(args.runtime)
        validate_authority(runtime, args.authority)
        args.cwd = (args.cwd or Path.cwd()).resolve()
        resolved_scope = None
        if args.command == "review":
            # Review is always read-only regardless of a conflicting flag.
            if args.authority != "ro":
                raise TossCapabilityError("review is read-only; --write is refused")
            prompt, resolved_scope = _review_prompt(args)
        else:
            prompt = _prompt(args)
        prompts = _review_chunks(prompt) if args.command == "review" else [prompt]
        print(json.dumps({
            "diagnostic": "delegation_resolved", "runtime": runtime.name,
            "cwd": str(args.cwd), "scope": resolved_scope, "chunks": len(prompts),
        }), file=sys.stderr)
        outputs: list[str] = []
        with runtime_environment(runtime) as child_env:
            executable_path = verify_runtime(runtime, env=child_env) if runtime.name == "tfcode" else None
            for index, chunk in enumerate(prompts, 1):
                final_path = state_dir() / f"final-{uuid.uuid4().hex}.txt" if runtime.name == "codex" else None
                try:
                    output = run(
                        command_for(
                            runtime, authority=args.authority, model=args.model, variant=args.variant,
                            output_file=final_path, executable_path=executable_path,
                        ),
                        chunk, runtime=runtime.name, cwd=args.cwd, timeout=args.timeout,
                        env=child_env, final_path=final_path,
                        extract_output=extract_tfcode_final if runtime.name == "tfcode" else None,
                        replace_env=runtime.name == "tfcode",
                        on_spool=lambda spool: print(json.dumps({
                            "diagnostic": "recovery_spool", "spool": str(spool),
                        }), file=sys.stderr, flush=True),
                    )
                except TossRunError:
                    if outputs:
                        sys.stdout.write(_format_review_outputs(outputs, len(prompts)))
                    print(json.dumps({
                        "diagnostic": "review_partial", "completed_chunks": len(outputs),
                        "total_chunks": len(prompts), "failed_chunk": index,
                    }), file=sys.stderr)
                    raise
                outputs.append(output)
        # stdout is intentionally only delegate content: callers can embed it verbatim.
        sys.stdout.write(_format_review_outputs(outputs, len(prompts)) if len(prompts) > 1 else outputs[0])
        return 0
    except TossRunError as exc:
        print(json.dumps(exc.structured()), file=sys.stderr)
        return 1
    except TossCapabilityError as exc:
        print(json.dumps({"error": "capability", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
