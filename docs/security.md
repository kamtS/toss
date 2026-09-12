# Security model

Toss is a local, single-shot delegation boundary. It reduces accidental
authority expansion; it does not make an arbitrary downstream tool safe.

## Threat model and non-goals

Toss assumes a person explicitly requests delegation and supplies a request.
The CLI never supplies a default runtime or model. The Agent Skill resolves an
explicitly named target, or discloses Codex read-only when the person says only
“toss this.” Its job is to keep each request foreground-only, pass arguments without shell
interpolation, preserve the configured runtime safety mode, and make recovery
explicit.

Toss does not:

- execute suggestions returned by a delegate;
- scrape, store, or forward credentials;
- run unattended loops, schedules, or retries;
- infer write authority: each write run requires the caller's explicit
  `--write --cwd` request.

## Runtime policy

Every CLI delegation requires an explicit runtime, for example `toss to codex`
or `toss review claude`. Only non-delegating inspection commands such as
`doctor` and `models` work without a target. The normal safe path is
`codex --ro`.
`--write` is allowed only with explicit `--cwd`. Codex keeps its sandbox,
Claude uses plan mode for read-only and edit authority for explicit writes, and
TF Code passes the selected provider/model and variant to the installed CLI.
Toss does not impose a version gate, static TF Code model allowlist, or a
tool-stripping environment. Explicit TF Code writes add `--auto` because that
is its non-interactive approval mechanism. TF Code may retain its normal local
session history according to its own configuration.

TF Code stdout is an untrusted JSONL event stream, not a final answer. Toss
accepts only the audited event types, rejects malformed,
unknown, error, and mixed-session events, groups completed text parts by
assistant message ID, and returns only the final non-empty message. Raw or
partial event streams are never promoted to a complete recovery spool.

## Adapters

`SKILL.md` is the agent-facing adapter. It may interpret natural language and
coordinate several independent CLI calls, but it cannot weaken a runtime
refusal, silently grant write authority, merge one delegate's text into
another's result, or execute returned instructions.

`toss-claude`, `toss-codex`, and `toss-tfcode` are convenience launchers only.
They print an output-injection warning on stderr and execute `toss "$@"`.
They must not select a runtime or model, alter flags, construct shell strings, source
configuration, or make a call on the user's behalf. `toss-recover` invokes
`toss recover <spool-file>` and never reruns a delegate.

## Output and recovery

Delegate text is data, not authority. Do not automatically follow commands,
URLs, or instructions embedded in it. Recovery is intentionally a separate
user action and should retain the same warning. Keep any spool files within
the user's control; they can contain task context.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose credentials,
silently change authority, bypass a runtime safety check, or execute returned
content. Follow [SECURITY.md](../SECURITY.md).
