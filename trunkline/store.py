"""Account metadata store. Secrets live in adapter-owned paths (review M-1);
~/.trunkline/ holds only ordering/mode/flags + published state.json."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fsutil import atomic_write, secure_dir


@dataclass
class Account:
    label: str
    provider: str


@dataclass
class StoreData:
    accounts: list[Account] = field(default_factory=list)
    active_by_provider: dict[str, str] = field(default_factory=dict)
    mode_by_provider: dict[str, str] = field(default_factory=dict)
    auto_switched: dict[str, bool] = field(default_factory=dict)
    preferred: dict[str, str] = field(default_factory=dict)
    primary_reset_at: dict[str, float] = field(default_factory=dict)


class AccountStore:
    def __init__(self, root: Path, codex_home: Path):
        self.root = root
        self.codex_home = codex_home
        self.meta_path = root / "accounts.json"
        self.state_path = root / "state.json"

    def load(self) -> StoreData:
        if not self.meta_path.exists():
            return StoreData()
        try:
            raw = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return StoreData(
                accounts=[Account(**a) for a in raw.get("accounts", [])],
                active_by_provider=dict(raw.get("active_by_provider", {})),
                mode_by_provider=dict(raw.get("mode_by_provider", {})),
                auto_switched=dict(raw.get("auto_switched", {})),
                preferred=dict(raw.get("preferred", {})),
                primary_reset_at=dict(raw.get("primary_reset_at", {})),
            )
        except Exception:
            # corrupt: back up, start empty — never silently destroy (Mobius failure #13)
            backup = self.meta_path.with_name(
                f"accounts.json.corrupt-{time.time_ns()}"
            )
            backup.write_bytes(self.meta_path.read_bytes())
            return StoreData()

    def save(self, data: StoreData) -> None:
        secure_dir(self.root)
        payload = {
            "accounts": [asdict(a) for a in data.accounts],
            "active_by_provider": data.active_by_provider,
            "mode_by_provider": data.mode_by_provider,
            "auto_switched": data.auto_switched,
            "preferred": data.preferred,
            "primary_reset_at": data.primary_reset_at,
        }
        atomic_write(self.meta_path, json.dumps(payload, indent=2).encode())

    def secret_path(self, account: Account) -> Path:
        if account.provider == "codex":
            return self.codex_home / "accounts" / account.label / "auth.json"
        raise ValueError(f"no secret path rule for provider {account.provider}")

    def labels(self, data: StoreData, provider: str) -> list[Account]:
        return [a for a in data.accounts if a.provider == provider]

    def write_state(self, state: dict) -> None:
        secure_dir(self.root)
        atomic_write(self.state_path, json.dumps(state, indent=2).encode(), mode=0o644)
