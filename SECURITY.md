# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through the repository's GitHub Security
Advisories page. Do not open a public issue for a vulnerability that could
expose credentials or account state.

Never attach real `auth.json`, credential, rollout log, or `~/.trunkline`
files. Replace account identifiers, emails, tokens, timestamps, and local
paths with synthetic values in every reproduction.

Include the affected commit, observed behavior, expected behavior, and a
minimal reproduction that does not contain secrets. Maintainers will
acknowledge the report and coordinate disclosure through the advisory.

## Supported versions

Until the first stable release, only the current `main` branch receives
security fixes.
