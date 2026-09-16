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

Delegate a text-only request with an explicit target and read-only intent:

```sh
toss to codex --model gpt-6-astra --ro -- "Review this design for missing safety constraints."
toss review codex --ro --base main
toss to tfcode --model toothfairyai/glm-5p3 --ro -- "Review these supplied requirements."
toss to tfcode --model provider/model --variant high --ro -- "Suggest three creative directions."
```

With the skill installed, the host agent can turn “have Astra and Fable review
this” into independent calls and return each response under its own untrusted
output label. Skill-level friendly names describe routing, not account
availability. `toss models` lists only Toss's built-in convenience aliases;
TF Code model and variant availability comes from the installed runtime and
its configuration.

Current authority contracts are intentionally uneven:

| Runtime | Read-only | Write | Notes |
| --- | --- | --- | --- |
| Codex | Yes | Explicit `--write --cwd` | Uses the Codex sandbox and final-message extractor. |
| Claude | Yes | No | Runs in safe mode with no tools or session persistence; it reviews only supplied text. |
| TF Code | Runtime plan mode | Explicit `--write --cwd` | `--ro` selects `plan` without Toss-added `--auto`; writes select `build --auto`. |

TF Code runs with the user's normal configuration and capabilities. Toss does
not provide an OS-enforced read-only sandbox for it: `--ro` selects TF Code's
`plan` agent and does not add `--auto`, but the runtime may still create plan
files such as `.tfcode/plans/` and its configured tools and permissions remain
authoritative. Any non-empty provider/model identifier and supported variant
are passed through as single `--model=<value>` and `--variant=<value>` argv
items; empty or flag-shaped values are refused.

The prompt is sent on stdin and only final completed assistant-message parts
from TF Code's JSON event stream are returned. Missing, malformed,
mixed-session, errored, or empty event streams fail closed. TF Code may retain
normal local session history according to its own configuration. `doctor` does
not make a model call or test account authentication; it reports TF Code plan
mode as runtime-managed, not enforced read-only.

Writing is explicit and requires a caller-supplied working directory:

```sh
toss to codex --write --cwd "$PWD" -- "Make this small, described change."
toss to tfcode --model provider/model --variant high --write --cwd "$PWD" -- "Implement this change."
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
- TF Code `--ro` is runtime plan mode without Toss-added auto-approval, not an
  OS-enforced read-only boundary; review the user's TF Code configuration.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). The public API is intentionally small; a feature
that silently expands authority is not an acceptable shortcut.
