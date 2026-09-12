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
toss to tfcode --model glm-5.3 --ro -- "Review these supplied requirements."
toss to tfcode --model glm-5.3-flash --ro -- "Suggest three creative directions."
toss to tfcode --model kimi-k3 --ro -- "Independently critique those directions."
```

With the skill installed, the host agent can turn “have Astra and Fable review
this” into independent calls and return each response under its own untrusted
output label. Model aliases describe routing, not account availability; use
`toss doctor` and `toss models` to inspect the local machine first.

Authority is selected explicitly per run. Toss does not keep a version-pinned
model allowlist or strip a runtime's normal capabilities:

| Runtime | Read-only | Write | Notes |
| --- | --- | --- | --- |
| Codex | Yes | Explicit `--write --cwd` | Uses the Codex sandbox; writes remain scoped to the selected workspace. |
| Claude | Yes | Yes | Read-only uses Claude plan mode; explicit writes use its edit authority. |
| TF Code | Yes | Yes | Any model identifier and supported variant pass through to the installed TF Code runtime. |

TF Code runs with the user's configured capabilities. Any provider/model string
and supported `--variant` pass straight through. `--write` adds TF Code's
non-interactive approval flag only because the caller explicitly asked it to
perform work. The prompt is still sent on stdin and Toss returns only the final
completed assistant-message parts from its JSON event stream. Missing,
malformed, mixed-session, errored, or empty event streams still fail closed.
`doctor` does not make a model call or test account authentication.

Writing is explicit on every runtime:

```sh
toss to codex --write --cwd "$PWD" -- "Make this small, described change."
toss to claude --model opus --write --cwd "$PWD" -- "Implement this change."
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
- Any installed runtime is used as configured. Model availability and account
  access are reported by that runtime rather than guessed by Toss.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). The public API is intentionally small; a feature
that silently expands authority is not an acceptable shortcut.
