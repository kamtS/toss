# Toss contributor guide

Toss is a public, foreground-only delegation CLI with a thin agent-facing
skill. Keep its default path safe:

- The CLI requires an explicit runtime. The agent skill may choose Codex as the
  disclosed fallback for an otherwise explicit “toss this” request because
  Codex can enforce read-only execution.
- TF Code has no verified noninteractive read-only mode. `toss to tfcode --ro`
  must refuse; `--write` is unsupported in v1.
- Do not add automatic execution, background jobs, credential handling, shell
  interpolation, or a pathway that silently expands authority.
- Core is Python standard library. Keep `SKILL.md` and host adapters thin;
  runtime and authority enforcement stay in Python and are separately tested.
- Stdout is reserved for a delegate's final message; diagnostics use stderr.
- Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`
  before proposing a source-tree change.

Repository-specific product decisions belong in `README.md` and `docs/security.md`.
