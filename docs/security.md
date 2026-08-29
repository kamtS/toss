# Security model

Toss is a local, single-shot delegation boundary. It reduces accidental
authority expansion; it does not make an arbitrary downstream tool safe.

## Threat model and non-goals

Toss assumes a person explicitly chooses a local runtime and supplies a
request. It never supplies a default runtime or model. Its job is to keep that
request foreground-only, pass arguments without shell
interpolation, preserve the configured runtime safety mode, and make recovery
explicit.

Toss does not:

- execute suggestions returned by a delegate;
- scrape, store, or forward credentials;
- run unattended loops, schedules, or retries;
- offer write execution except where a runtime has an explicit, tested write
  authority contract (currently Codex with a user-supplied `--cwd`);
- turn TF Code into a verified read-only non-interactive runtime.

## Runtime policy

Every delegation requires an explicit runtime, for example `toss to codex` or
`toss review claude`. Only non-delegating inspection commands such as `doctor`
and `models` work without a target. The normal safe path is `codex --ro`.
`codex --write` is allowed only with explicit `--cwd`; it does not bypass the
runtime's own approval policy. TF Code has no verified noninteractive read-only
mode. `toss to tfcode --ro` must refuse, and `--write` is unsupported in v1. A
future runtime is not added by renaming an adapter: it needs an explicit, tested
authority model.

## Adapters

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
