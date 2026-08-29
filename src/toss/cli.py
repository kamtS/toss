"""The small, deliberately conservative Toss command-line interface."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

from .runner import TossRunError, recover, run, state_dir
from .runtimes import TossCapabilityError, command_for, doctor, get_runtime, models


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toss")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p_models = commands.add_parser("models")
    p_models.add_argument("runtime", choices=["codex", "claude", "tfcode"], nargs="?")
    def delegation(name: str) -> argparse.ArgumentParser:
        item = commands.add_parser(name)
        # A delegation must name its destination. This prevents surprise model
        # execution and leaves every hand-off visible in shell history.
        item.add_argument("runtime", choices=["codex", "claude", "tfcode"])
        item.add_argument("--model")
        item.add_argument("--variant")
        authority = item.add_mutually_exclusive_group()
        authority.add_argument("--ro", action="store_const", const="ro", dest="authority")
        authority.add_argument("--write", action="store_const", const="write", dest="authority")
        item.set_defaults(authority="ro")
        item.add_argument("--cwd", type=Path)
        item.add_argument("--timeout", type=float, default=120.0)
        return item
    delegation("to")
    review = delegation("review")
    review.add_argument("--base", default="HEAD")
    review.add_argument("--scope", choices=["auto", "working-tree", "branch"], default="auto")
    recover_parser = commands.add_parser("recover")
    recover_parser.add_argument("spool", type=Path)
    return parser


def _prompt(args: argparse.Namespace) -> str:
    if args.command == "review":
        diff_args = ["git", "diff", args.base]
        if args.scope == "branch":
            diff_args = ["git", "diff", f"{args.base}...HEAD"]
        result = subprocess.run(diff_args, cwd=args.cwd, capture_output=True, text=True)
        diff = result.stdout if result.returncode == 0 else "(diff unavailable)"
        return "Review this change. Identify concrete risks and suggested fixes.\n\n" + diff
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
        saved = recover(args.spool)
        output = saved.get("output", "")
        if not saved.get("complete"):
            print(json.dumps({"error": "partial_spool", "spool": str(args.spool)}), file=sys.stderr)
            return 1
        sys.stdout.write(str(output))
        return 0
    try:
        runtime = get_runtime(args.runtime)
        cwd_was_supplied = args.cwd is not None
        args.cwd = (args.cwd or Path.cwd()).resolve()
        if args.authority == "write" and not cwd_was_supplied:
            raise TossCapabilityError("--write requires an explicit --cwd")
        prompt = _prompt(args)
        final_path = state_dir() / f"final-{uuid.uuid4().hex}.txt" if runtime.name == "codex" else None
        output = run(
            command_for(runtime, authority=args.authority, model=args.model, variant=args.variant, output_file=final_path),
            prompt, runtime=runtime.name, cwd=args.cwd, timeout=args.timeout, final_path=final_path,
        )
        # stdout is intentionally only delegate content: callers can embed it verbatim.
        sys.stdout.write(output)
        return 0
    except TossRunError as exc:
        print(json.dumps(exc.structured()), file=sys.stderr)
        return 1
    except TossCapabilityError as exc:
        print(json.dumps({"error": "capability", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
