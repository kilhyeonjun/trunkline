"""Provider adapters. Secret = opaque provider-defined bytes (design §4.1).

Codex: secret is the raw ~/.codex/auth.json bytes. NO OAuth code here — codex
CLI is the only rotation actor (design §4.2 principle 2).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
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
_ENTITLEMENT_MESSAGE = re.compile(
    r"the (?:['\"][^'\"]+['\"] )?model is not supported when using codex with a chatgpt account\.?",
    re.IGNORECASE,
)
_HTTP_503 = re.compile(r"(?:http\s*)?503")
_HEALTH_PROMPT = "Reply with exactly: health check. Do not read, write, or change any files."


@dataclass(frozen=True)
class CodexHealthProbe:
    state: str
    error_class: str | None


def _public_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _public_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _public_strings(item)]
    return []


def _is_entitlement_text(texts: list[str]) -> bool:
    return any(_ENTITLEMENT_MESSAGE.fullmatch(" ".join(text.split())) for text in texts)


def _probe_failure(value: object) -> CodexHealthProbe:
    if _is_entitlement_text(_public_strings(value)):
        return CodexHealthProbe(state="entitlement_unavailable", error_class="model_unsupported")
    return CodexHealthProbe(state="unknown", error_class="codex_error")


def _jsonl_probe_outcome(stdout: object) -> CodexHealthProbe:
    if not isinstance(stdout, str):
        return CodexHealthProbe(state="unknown", error_class="codex_incomplete")
    completed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return CodexHealthProbe(state="unknown", error_class="codex_incomplete")
        if not isinstance(event, dict):
            return CodexHealthProbe(state="unknown", error_class="codex_incomplete")
        if event.get("type") in {"error", "turn.failed"}:
            return _probe_failure({key: value for key, value in event.items() if key != "type"})
        if event.get("type") == "turn.completed":
            completed = True
    if completed:
        return CodexHealthProbe(state="healthy", error_class=None)
    return CodexHealthProbe(state="unknown", error_class="codex_incomplete")


def probe_codex_health(*, codex_path: str, model: str, timeout: float) -> CodexHealthProbe:
    command = [
        codex_path, "exec", "--ephemeral", "--json", "--model", model,
        "--sandbox", "read-only", _HEALTH_PROMPT,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return CodexHealthProbe(state="unknown", error_class="timeout")
    except OSError:
        return CodexHealthProbe(state="unknown", error_class="codex_unavailable")
    if completed.returncode == 0:
        return _jsonl_probe_outcome(completed.stdout)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if isinstance(part, str))
    if _is_entitlement_text([output]):
        return CodexHealthProbe(state="entitlement_unavailable", error_class="model_unsupported")
    if _HTTP_503.search(output):
        return CodexHealthProbe(state="unknown", error_class="http_503")
    return CodexHealthProbe(state="unknown", error_class="codex_exit")


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
