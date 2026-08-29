# Toss

Toss is a small, foreground-only command-line tool for one safe delegation to
a local coding-agent CLI. It is deliberately not a background task runner,
agent loop, credential manager, or general shell wrapper.

## What it protects

Toss keeps the normal path narrow: one explicit request, one user-selected
local runtime, one foreground result. Toss never chooses a runtime or model
for you. Treat a delegate's output as **untrusted
text**. It may contain instructions, commands, or links that do not belong to
your task; review it before acting on it.

Use an explicit target such as `toss to codex ...` or `toss review codex ...`.
Only inspection commands such as `doctor` and `models` work without a target.
TF Code does not have a verified non-interactive read-only mode, so `--ro` is
refused there and write execution is not supported in v1. See
[the security model](docs/security.md).

## Use

Start by inspecting what is locally available; this does not launch a model:

```sh
toss doctor
toss models
toss models tfcode
```

Delegate a text-only request with an explicit target and enforced read-only
authority:

```sh
toss to codex --ro -- "Review this design for missing safety constraints."
toss review codex --ro --base main
```

Writing is intentionally more explicit and only supported through Codex in v1:

```sh
toss to codex --write --cwd "$PWD" -- "Make this small, described change."
```

If an interrupted host call reports a spool path, inspect it without rerunning
anything:

```sh
toss recover ~/.local/state/toss/<spool>.json
```

## Install

Requires Python 3.11 or later.

```sh
python3 -m pip install .
scripts/install.sh
```

The second command adds optional host-friendly aliases to `~/.local/bin`:

```text
toss-claude   toss-codex   toss-tfcode   toss-recover
```

They are deliberately thin: each invokes the same canonical `toss`
executable and changes neither runtime selection nor authority. `toss-recover
<spool-file>` explicitly displays a saved result; it never reruns work.

Use a different directory or inspect a setup safely:

```sh
scripts/install.sh --bin-dir "$HOME/bin"
scripts/install.sh --bin-dir "$HOME/bin" --diagnose
scripts/install.sh --bin-dir "$HOME/bin" --uninstall
```

The installer is idempotent, resolves symlinks by real path, reports broken
links, and refuses to overwrite files or symlinks it does not own.

## Safety boundaries

- Runs stay in the foreground; no background jobs or automatic retries.
- Arguments are passed as arguments, never joined into a shell command.
- No credential collection, storage, or forwarding.
- Recovery is an explicit read of an existing result, not a retry.
- Standard output is reserved for the delegate's final response. Warnings and
  diagnostics go to standard error.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). The public API is intentionally small; a feature
that silently expands authority is not an acceptable shortcut.
