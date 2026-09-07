# Contributing to Toss

Thanks for helping keep Toss small and dependable.

## Development

Use Python 3.11+ and run the complete source-tree check before opening a pull
request. Setting `PYTHONPATH` is required until the package is installed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

To exercise the installed console entry point in an isolated environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/toss --help
```

Keep core code in the standard library. `SKILL.md` interprets natural language
and may coordinate independent calls, but runtime commands and authority checks
belong to the canonical CLI. Shell adapters remain separately testable: they
may warn and `exec toss "$@"`, but cannot broaden authority, interpolate a
shell command, or consume secrets.

## Change principles

- Preserve foreground, single-shot behaviour.
- Put diagnostics on stderr; reserve stdout for the final delegate output.
- Add tests for refusal paths and recovery behavior, not only happy paths.
- Runtime contracts tied to a particular binary must exact-gate the audited
  version and use fake executables in tests; validation must never call a live
  model.
- For machine-readable runtimes, parse only the documented final-message shape
  and fail closed on malformed, unknown, errored, mixed, or empty output.
- Document safety implications in `docs/security.md` when changing a runtime,
  adapter, spool format, or install path.
- Do not submit credentials, tokens, real prompts, or captured delegate output.

Contributions are licensed under Apache-2.0, as described in [LICENSE](LICENSE).
