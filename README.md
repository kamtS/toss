# Toss

Toss is the agent-facing “get another mind on this” gesture:

> Toss this to Claude.
>
> Have Astra and Fable review this change.

A portable Agent Skill interprets the request and a small, deterministic CLI
performs each local delegation. Toss is deliberately not a background task
runner, credential manager, or general shell wrapper.

## What it protects

Toss keeps each underlying run narrow: one explicit request, one resolved local
runtime, one foreground result. Several-reviewer requests become several
independent runs, never a shared writer or hidden agent loop. Treat every
delegate's output as **untrusted text**. It may contain instructions, commands,
or links that do not belong to your task; review it before acting on it.

The canonical CLI requires an explicit target such as `toss to codex ...` or
`toss review claude ...`. The Agent Skill resolves natural model names, keeps
multi-reviewer outputs separate and labelled, and uses Codex read-only as a
disclosed fallback only when the user explicitly asks to “toss this” without
naming a target. See [the security model](docs/security.md).

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
toss to codex --model gpt-6-astra --ro -- "Review this design for missing safety constraints."
toss review codex --ro --base main
```

With the skill installed, the host agent can turn “have Astra and Fable review
this” into independent calls and return each response under its own untrusted
output label. Model aliases describe routing, not account availability; use
`toss doctor` and `toss models` to inspect the local machine first.

Current v1 authority contracts are intentionally uneven:

| Runtime | Read-only | Write | Notes |
| --- | --- | --- | --- |
| Codex | Yes | Explicit `--write --cwd` | Uses the Codex sandbox and final-message extractor. |
| Claude | Yes | No | Runs in safe mode with no tools or session persistence; it reviews only supplied text. |
| TF Code | Refused | Refused | No enforceable non-interactive read-only contract has been verified yet. |

That means Kimi and Grok are not routable in v1 unless a future verified
runtime contract lists them. Toss reports the unsupported target instead of
guessing a route or weakening the boundary. `doctor` does not make a model
call or test account authentication, and `models` currently reports vetted
static aliases rather than live provider discovery.

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

Requires Python 3.11 or later. Install the CLI, then link the portable skill
into each host where you want the natural-language gesture:

```sh
python3 -m pip install .
scripts/install.sh --skill-dir "$HOME/.codex/skills"
scripts/install.sh --skill-dir "$HOME/.claude/skills"
```

The installer adds optional host-friendly aliases to `~/.local/bin` and, when
`--skill-dir` is supplied, links this repository at `<skill-dir>/toss` so the
host discovers `SKILL.md`:

```text
toss-claude   toss-codex   toss-tfcode   toss-recover
```

They are deliberately thin: each invokes the same canonical `toss`
executable and changes neither runtime selection nor authority. `toss-recover
<spool-file>` explicitly displays a saved result; it never reruns work.

Use a different directory or inspect a setup safely:

```sh
scripts/install.sh --bin-dir "$HOME/bin"
scripts/install.sh --bin-dir "$HOME/bin" --skill-dir "$HOME/.codex/skills" --diagnose
scripts/install.sh --bin-dir "$HOME/bin" --skill-dir "$HOME/.codex/skills" --uninstall
```

The installer checks that the canonical `toss` executable is on `PATH`, is
idempotent, resolves symlinks by real path, reports broken links, and refuses
to overwrite files or symlinks it does not own.

Source lives at [github.com/kamtS/toss](https://github.com/kamtS/toss).

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
