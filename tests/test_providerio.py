import json
import os
from pathlib import Path

import pytest

from trunkline.providerio import CodexConfigIO

AUTH = json.dumps({"tokens": {"account_id": "acct-1"}}).encode()


def test_read_live_secret(codex_home: Path):
    (codex_home / "auth.json").write_bytes(AUTH)
    io = CodexConfigIO(codex_home)
    assert io.read_live_secret() == AUTH


def test_recognizes_codex_shapes(codex_home: Path):
    io = CodexConfigIO(codex_home)
    assert io.recognizes_secret(b'{"tokens": {}}')
    assert io.recognizes_secret(b'{"OPENAI_API_KEY": "sk-x"}')
    assert io.recognizes_secret(b'{"auth_mode": "chatgpt"}')
    assert not io.recognizes_secret(b'{"claudeAiOauth": {}}')
    assert not io.recognizes_secret(b"garbage")


def test_write_live_secret_atomic_0600(codex_home: Path):
    io = CodexConfigIO(codex_home)
    io.write_live_secret(AUTH)
    p = codex_home / "auth.json"
    assert p.read_bytes() == AUTH
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_write_live_secret_unlinks_symlink(codex_home: Path):
    """리뷰 C-4: 심링크면 unlink 후 실파일로 — realpath(스토어 원본)에 쓰지 않는다."""
    store = codex_home / "accounts" / "personal"
    store.mkdir(parents=True)
    original = store / "auth.json"
    original.write_bytes(b'{"tokens": {"account_id": "old"}}')
    live = codex_home / "auth.json"
    live.symlink_to(original)

    io = CodexConfigIO(codex_home)
    io.write_live_secret(AUTH)

    assert not live.is_symlink()          # 실파일로 전환됨
    assert live.read_bytes() == AUTH
    assert original.read_bytes() == b'{"tokens": {"account_id": "old"}}'  # 원본 무오염


def test_write_rejects_unrecognized(codex_home: Path):
    io = CodexConfigIO(codex_home)
    with pytest.raises(ValueError):
        io.write_live_secret(b'{"claudeAiOauth": {}}')


def test_live_identity(codex_home: Path):
    (codex_home / "auth.json").write_bytes(AUTH)
    io = CodexConfigIO(codex_home)
    assert io.live_identity().account_id == "acct-1"


def test_live_identity_missing_file(codex_home: Path):
    io = CodexConfigIO(codex_home)
    assert io.live_identity() is None
