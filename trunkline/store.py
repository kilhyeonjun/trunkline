"""Account metadata store. Secrets live in adapter-owned paths (review M-1);
~/.trunkline/ holds only ordering/mode/flags + published state.json."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fsutil import atomic_write, secure_dir


ACCOUNT_HEALTH_LIMIT = 100
ACCOUNT_HEALTH_KEYS = frozenset({
    "provider", "label", "model", "state", "observed_at", "reset_at", "error_class",
})


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
    account_health: list[dict[str, object]] = field(default_factory=list)


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
                account_health=self._clean_health(raw.get("account_health", [])),
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
            "account_health": self._clean_health(data.account_health),
        }
        atomic_write(self.meta_path, json.dumps(payload, indent=2).encode())

    def secret_path(self, account: Account) -> Path:
        if account.provider == "codex":
            return self.codex_home / "accounts" / account.label / "auth.json"
        raise ValueError(f"no secret path rule for provider {account.provider}")

    def labels(self, data: StoreData, provider: str) -> list[Account]:
        return [a for a in data.accounts if a.provider == provider]

    @staticmethod
    def _clean_health(records: object) -> list[dict[str, object]]:
        if not isinstance(records, list):
            return []
        clean = []
        for record in records:
            if not isinstance(record, dict):
                continue
            values = {key: record.get(key) for key in ACCOUNT_HEALTH_KEYS}
            valid_strings = all(
                isinstance(values[key], str) and values[key]
                for key in ("provider", "label", "model", "state")
            )
            valid_observed_at = not isinstance(values["observed_at"], bool) and isinstance(
                values["observed_at"], int
            )
            valid_reset_at = values["reset_at"] is None or (
                not isinstance(values["reset_at"], bool) and isinstance(values["reset_at"], int)
            )
            valid_error_class = values["error_class"] is None or isinstance(
                values["error_class"], str
            )
            if valid_strings and valid_observed_at and valid_reset_at and valid_error_class:
                clean.append(values)
        return clean[-ACCOUNT_HEALTH_LIMIT:]

    def record_account_health(self, *, provider: str, label: str, model: str,
                              state: str, observed_at: int, reset_at: int | None = None,
                              error_class: str | None = None, **_ignored: object) -> None:
        record = self._clean_health([{
            "provider": provider, "label": label, "model": model, "state": state,
            "observed_at": observed_at, "reset_at": reset_at, "error_class": error_class,
        }])
        if not record:
            return
        data = self.load()
        triple = (provider, label, model)
        data.account_health = [
            item for item in data.account_health
            if (item["provider"], item["label"], item["model"]) != triple
        ] + record
        data.account_health = self._clean_health(data.account_health)
        self.save(data)

    def account_health_for_provider(self, provider: str) -> list[dict[str, object]]:
        return [record for record in self.load().account_health if record["provider"] == provider]

    def write_state(self, state: dict) -> None:
        secure_dir(self.root)
        atomic_write(self.state_path, json.dumps(state, indent=2).encode(), mode=0o644)
