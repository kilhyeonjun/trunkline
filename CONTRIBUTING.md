# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Development rules

- Never commit real credentials, account state, emails, or provider logs.
- Use synthetic fixtures for authentication payloads.
- Write a failing test before changing behavior.
- Keep token handling local and preserve the no-refresh contract.
- Avoid dependencies unless the standard library cannot meet the requirement.

Run the Python suite:

```bash
python3 -m pytest -q
```

Run the Swift suite:

```bash
cd menubar
swift test
```

Before opening a pull request, run:

```bash
bash scripts/audit-public-tree.sh
```

By contributing, you agree that your contribution is licensed under the
project's MIT License.
