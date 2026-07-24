"""Switching = byte swap of adapter-owned snapshots (design §4.4).

Live is the source of truth; we follow it (reconcile), never fight it.
Before leaving an account we absorb the live bytes back into its profile so
CLI-rotated tokens are not lost (Mobius Switcher.swift:105-126 port).
"""
from __future__ import annotations

from .fsutil import UnstableFileError, atomic_write
from .identity import decode_identity
from .providerio import ProviderConfigIO
from .store import Account, AccountStore


class SwitchError(RuntimeError):
    pass


class Switcher:
    def __init__(self, store: AccountStore, ios: dict[str, ProviderConfigIO]):
        self.store = store
        self.ios = ios

    def _account(self, provider: str, label: str) -> Account:
        data = self.store.load()
        for a in self.store.labels(data, provider):
            if a.label == label:
                return a
        raise SwitchError(f"unknown account: {provider}/{label}")

    def _match_label(self, provider: str, live_bytes: bytes) -> str | None:
        live_ident = decode_identity(live_bytes)
        if live_ident is None:
            return None
        data = self.store.load()
        for a in self.store.labels(data, provider):
            path = self.store.secret_path(a)
            if not path.exists():
                continue
            snap = decode_identity(path.read_bytes())
            if snap is None:
                continue
            if live_ident.account_id and snap.account_id:
                if live_ident.account_id == snap.account_id:
                    return a.label
                continue
            if live_ident.email and live_ident.email == snap.email:
                return a.label
        return None

    def current_label(self, provider: str) -> str | None:
        io = self.ios[provider]
        try:
            return self._match_label(provider, io.read_live_secret())
        except OSError:
            return None

    def _save_back(self, provider: str, live_bytes: bytes) -> None:
        """Absorb live (possibly CLI-rotated) bytes into the matching profile."""
        label = self._match_label(provider, live_bytes)
        if label is None:
            return  # unknown live identity — do not guess a destination
        path = self.store.secret_path(self._account(provider, label))
        atomic_write(path, live_bytes)

    def switch(self, provider: str, label: str, *, auto: bool = False) -> None:
        io = self.ios[provider]
        target = self._account(provider, label)

        previous: bytes | None = None
        try:
            previous = io.read_stable_live_secret()
            self._save_back(provider, previous)
        except (OSError, UnstableFileError):
            previous = None  # 라이브 없음/불안정 — 되저장 생략하고 진행

        # save-back may have just absorbed rotated live bytes into this same
        # profile (switch-to-self) — read target bytes AFTER, or a self-switch
        # would revert live to the stale pre-rotation snapshot.
        target_bytes = self.store.secret_path(target).read_bytes()

        try:
            io.write_live_secret(target_bytes)
        except Exception:
            if previous is not None:
                io.write_live_secret(previous)  # 롤백
            raise

        data = self.store.load()
        data.active_by_provider[provider] = label
        data.auto_switched[provider] = auto
        self.store.save(data)

    def adopt(self, provider: str, label: str) -> None:
        data = self.store.load()
        if any(a.label == label for a in self.store.labels(data, provider)):
            raise SwitchError(f"label exists: {provider}/{label} (재로그인은 login 커맨드)")
        io = self.ios[provider]
        live = io.read_stable_live_secret()
        account = Account(label, provider)
        atomic_write(self.store.secret_path(account), live)
        data.accounts.append(account)
        data.active_by_provider.setdefault(provider, label)
        self.store.save(data)

    def reconcile(self, provider: str) -> bool:
        io = self.ios[provider]
        try:
            live_label = self._match_label(provider, io.read_live_secret())
        except OSError:
            return False
        if live_label is None:
            return False
        data = self.store.load()
        if data.active_by_provider.get(provider) != live_label:
            data.active_by_provider[provider] = live_label
            self.store.save(data)
            return True
        return False
