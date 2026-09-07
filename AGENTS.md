# Toss contributor guide

Toss is a public, foreground-only delegation CLI with a thin agent-facing
skill. Keep its default path safe:

- The CLI requires an explicit runtime. The agent skill may choose Codex as the
  disclosed fallback for an otherwise explicit “toss this” request because
  Codex can enforce read-only execution.
- TF Code read-only is a tool-free contract limited to explicitly audited TF
  Code versions (currently 2.3.0 and 2.4.0) and a verified command surface:
  deny all permissions, isolate configuration, disable plugins/skills/prompts,
  loops, sharing, and formatting, use JSON output, and extract only its final
  assistant message. TF Code write must always refuse.
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
