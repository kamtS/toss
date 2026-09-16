# Toss contributor guide

Toss is a public, foreground-only delegation CLI with a thin agent-facing
skill. Keep its default path safe:

- The CLI requires an explicit runtime. The agent skill may choose Codex as the
  disclosed fallback for an otherwise explicit “toss this” request because
  Codex can enforce read-only execution.
- TF Code `--ro` selects its `plan` agent without adding `--auto`; this is a
  runtime policy, not OS-enforced read-only, and may create TF Code plan files.
  Explicit `--write --cwd` selects `build --auto`. Preserve the user's TF Code
  configuration, models, variants, and capabilities rather than maintaining a
  Toss allowlist or isolated deny-all environment.
- Do not add automatic execution, background jobs, credential handling, shell
  interpolation, or a pathway that silently expands authority.
- Core is Python standard library. Keep `SKILL.md` and host adapters thin;
  runtime and authority enforcement stay in Python and are separately tested.
- Stdout is reserved for a delegate's final message; diagnostics use stderr.
- Tests must use fake runtimes; never spend tokens or invoke a live model from
  the test suite.
- Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`
  before proposing a source-tree change.

Repository-specific product decisions belong in `README.md` and `docs/security.md`.
