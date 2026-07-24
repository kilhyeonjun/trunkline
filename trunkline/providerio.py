"""Provider adapters. Secret = opaque provider-defined bytes (design §4.1).

Codex: secret is the raw ~/.codex/auth.json bytes. NO OAuth code here — codex
CLI is the only rotation actor (design §4.2 principle 2).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .fsutil import atomic_write, stable_read
from .identity import Identity, decode_identity


class ProviderConfigIO(Protocol):
    provider: str

    def read_live_secret(self) -> bytes: ...
    def live_identity(self) -> Identity | None: ...
    def read_stable_live_secret(self, gap: float = 0.7) -> bytes: ...
    def write_live_secret(self, data: bytes) -> None: ...
    def recognizes_secret(self, data: bytes) -> bool: ...


# auth.json 최상위 키로 형태 판별 (Mobius CodexConfigIO.swift:61-76 이식)
_CODEX_TOP_KEYS = {"tokens", "auth_mode", "OPENAI_API_KEY"}


class CodexConfigIO:
    provider = "codex"

    def __init__(self, codex_home: Path):
        self.codex_home = codex_home
        self.live_path = codex_home / "auth.json"

    def read_live_secret(self) -> bytes:
        return self.live_path.read_bytes()

    def live_identity(self) -> Identity | None:
        try:
            return decode_identity(self.read_live_secret())
        except OSError:
            return None

    def read_stable_live_secret(self, gap: float = 0.7) -> bytes:
        return stable_read(self.live_path, gap=gap)

    def write_live_secret(self, data: bytes) -> None:
        if not self.recognizes_secret(data):
            raise ValueError("refusing to write non-codex bytes to codex live path")
        # 리뷰 C-4: 심링크(구 codex-account 토폴로지)면 해소 후 실파일 쓰기.
        # realpath에 쓰면 스토어 원본이 오염된다.
        if self.live_path.is_symlink():
            self.live_path.unlink()
        atomic_write(self.live_path, data)

    def recognizes_secret(self, data: bytes) -> bool:
        try:
            obj = json.loads(data)
        except Exception:
            return False
        return isinstance(obj, dict) and bool(_CODEX_TOP_KEYS & obj.keys())
