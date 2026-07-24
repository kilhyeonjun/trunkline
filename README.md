# Trunkline

Trunkline is a local-first account manager for AI coding tools. It keeps named
local snapshots of Codex authentication, switches the active snapshot, watches
local usage events, and can move to a fallback account when the active account
is exhausted. A native macOS menu bar app shows status and runs an allowlisted
set of CLI actions.

> [!WARNING]
> Trunkline replaces local authentication files when switching accounts.
> Back up your existing credentials before initialization and test with
> non-critical accounts first. Never commit or share files from `~/.codex`,
> `~/.claude`, or `~/.trunkline`.

Trunkline is alpha software. The current provider implementation is
Codex-first, with read-only Claude status display.

## Requirements

- macOS 14 or later for the menu bar app
- Python 3.11 or later
- `pipx`
- Xcode/Swift 6 only when building the menu bar app from source

## Install the CLI

Install the v0.1.0 wheel from GitHub Releases:

```bash
pipx install https://github.com/kilhyeonjun/trunkline/releases/download/v0.1.0/trunkline-0.1.0-py3-none-any.whl
trunkline --help
```

Verify the downloaded wheel against the published
`trunkline-0.1.0-py3-none-any.whl.sha256` file before installation when
downloading it manually.

Initialize two named snapshots after backing up your current credentials:

```bash
trunkline init --priority personal,company
trunkline status
trunkline pin personal
trunkline auto
```

`pin LABEL` keeps the selected account active. `auto` enables fallback and
return decisions based on locally observed usage events.

## Install the menu bar app and daemon

Clone the repository after installing the CLI, then run:

```bash
bash scripts/install.sh
```

The installer resolves the installed `trunkline` executable, builds the
menu bar app, installs it under `~/Applications`, and creates a user
LaunchAgent. It does not inject a source checkout through `PYTHONPATH`.

Remove the app and LaunchAgent with:

```bash
bash scripts/uninstall.sh
```

Uninstalling preserves `~/.trunkline`. To explicitly remove Trunkline's local
state and account snapshots:

```bash
bash scripts/uninstall.sh --remove-data
```

## Safety and network behavior

- Account credential files are treated as opaque bytes during switching.
- Stored metadata does not contain access or refresh token values.
- Usage readers send an existing access token only to the provider's usage
  endpoint; they do not refresh, rotate, print, or persist returned tokens.
- The daemon watches local rollout logs and state. It does not add a token
  refresh path.
- The menu bar app only permits `status`, `usage`, `switch`, `pin`, `auto`,
  and `lock`.

Read the implementation and tests before trusting Trunkline with important
accounts. See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Architecture

- `trunkline/`: Python CLI, account store, switcher, event router, and daemon
- `menubar/`: Swift package for the native macOS menu bar app
- `scripts/install.sh`: app build and user LaunchAgent installation
- `scripts/uninstall.sh`: conservative removal with data preservation
- `scripts/claude-statusline.sh`: optional local Claude usage status bridge

Runtime state lives under `~/.trunkline`; provider credentials remain in their
provider-owned locations.

## Development

Run Python tests:

```bash
python3 -m pytest -q
```

Run Swift tests:

```bash
cd menubar
swift test
```

Run the public release audit:

```bash
bash scripts/audit-public-tree.sh
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## Limitations

- macOS is the only supported desktop platform.
- Codex is the only provider with account switching.
- The app is currently ad-hoc signed and built from source.
- Automatic updates, notarized releases, and Homebrew distribution are not
  implemented.

## License

Trunkline is released under the [MIT License](LICENSE). Portions derived from
other MIT-licensed projects are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
