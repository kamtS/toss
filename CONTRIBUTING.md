# Contributing to Toss

Thanks for helping keep Toss small and dependable.

## Development

Use Python 3.11+ and run the complete local check before opening a pull
request:

```sh
python3 -m unittest discover -s tests -v
python3 -m pip install .
```

Keep core code in the standard library. Adapters are shell-thin and separately
testable: they may warn and `exec toss "$@"`, but cannot choose a runtime or
model, broaden authority, interpolate a shell command, or consume secrets.

## Change principles

- Preserve foreground, single-shot behaviour.
- Put diagnostics on stderr; reserve stdout for the final delegate output.
- Add tests for refusal paths and recovery behavior, not only happy paths.
- Document safety implications in `docs/security.md` when changing a runtime,
  adapter, spool format, or install path.
- Do not submit credentials, tokens, real prompts, or captured delegate output.

Contributions are licensed under Apache-2.0, as described in [LICENSE](LICENSE).
