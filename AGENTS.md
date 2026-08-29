# Toss contributor guide

Toss is a public, foreground-only delegation CLI. Keep its default path safe:

- Codex is the default runtime because it can enforce read-only execution.
- TF Code has no verified noninteractive read-only mode. `toss to tfcode --ro`
  must refuse; `--write` is unsupported in v1.
- Do not add automatic execution, background jobs, credential handling, shell
  interpolation, or a pathway that silently expands authority.
- Core is Python standard library. Keep host adapters thin and separately tested.
- Stdout is reserved for a delegate's final message; diagnostics use stderr.
- Run `python3 -m unittest discover -s tests -v` before proposing a change.

Repository-specific product decisions belong in `README.md` and `docs/security.md`.
