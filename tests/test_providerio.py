import json
import os
import subprocess
from pathlib import Path

import pytest

from trunkline.providerio import CodexConfigIO, probe_codex_health

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


def test_probe_uses_one_read_only_ephemeral_json_codex_exec(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"type":"turn.completed"}\n', stderr="")

    monkeypatch.setattr("trunkline.providerio.subprocess.run", run)

    result = probe_codex_health(codex_path="codex", model="gpt-5.6-sol", timeout=3)

    assert result.state == "healthy"
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert kwargs["timeout"] == 3
    assert "health check" in command[-1].casefold()


@pytest.mark.parametrize(
    ("stdout", "expected_state", "expected_error"),
    [
        ('{"type":"error","error":{"message":"The model is not supported when using Codex with a ChatGPT account."}}\n',
         "entitlement_unavailable", "model_unsupported"),
        ('{"type":"turn.failed","error":{"detail":{"message":"The model is not supported when using Codex with a ChatGPT account."}}}\n',
         "entitlement_unavailable", "model_unsupported"),
        ('{"type":"error","message":"arbitrary provider failure"}\n{"type":"turn.completed"}\n',
         "unknown", "codex_error"),
        ('{"type":"error","message":"arbitrary provider failure"}\n', "unknown", "codex_error"),
        ('{"type":"item.completed"}\n', "unknown", "codex_incomplete"),
        ('not-json\n', "unknown", "codex_incomplete"),
    ],
)
def test_zero_exit_probe_requires_completed_jsonl_without_error(monkeypatch, stdout,
                                                                 expected_state, expected_error):
    completed = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
    monkeypatch.setattr("trunkline.providerio.subprocess.run", lambda *_args, **_kwargs: completed)

    result = probe_codex_health(codex_path="codex", model="gpt-5.6-sol", timeout=3)

    assert (result.state, result.error_class) == (expected_state, expected_error)
    assert not hasattr(result, "stdout")


@pytest.mark.parametrize(
    ("completed", "expected_state", "expected_error"),
    [
        (subprocess.CompletedProcess([], 1, stdout="HTTP 503", stderr=""), "unknown", "http_503"),
        (subprocess.CompletedProcess([], 1, stdout="The model is not supported when using Codex with a ChatGPT account.", stderr=""), "entitlement_unavailable", "model_unsupported"),
    ],
)
def test_probe_normalizes_public_outcomes_without_raw_output(monkeypatch, completed,
                                                              expected_state, expected_error):
    monkeypatch.setattr("trunkline.providerio.subprocess.run", lambda *_args, **_kwargs: completed)

    result = probe_codex_health(codex_path="codex", model="gpt-5.6-sol", timeout=3)

    assert result.state == expected_state
    assert result.error_class == expected_error
    assert not hasattr(result, "stdout")


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected_state", "expected_error"),
    [
        ('{"type":"error","message":"The model is not supported when using Codex with a ChatGPT account."}\n', "",
         "entitlement_unavailable", "model_unsupported"),
        ('{"type":"turn.failed","error":{"message":"The model is not supported when using Codex with a ChatGPT account."}}\n', "",
         "entitlement_unavailable", "model_unsupported"),
        ('{"type":"error","message":"HTTP 503"}\n', "", "unknown", "http_503"),
        ("not-json\n", "plain failure", "unknown", "codex_exit"),
    ],
)
def test_nonzero_probe_parses_jsonl_failure_before_plain_fallback(monkeypatch, stdout, stderr,
                                                                  expected_state, expected_error):
    completed = subprocess.CompletedProcess([], 1, stdout=stdout, stderr=stderr)
    monkeypatch.setattr("trunkline.providerio.subprocess.run", lambda *_args, **_kwargs: completed)

    result = probe_codex_health(codex_path="codex", model="gpt-5.6-sol", timeout=3)

    assert (result.state, result.error_class) == (expected_state, expected_error)
    assert not hasattr(result, "stdout")


def test_probe_timeout_is_unknown_without_raw_output(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("codex", 3, output="secret-token", stderr="email@example.com")

    monkeypatch.setattr("trunkline.providerio.subprocess.run", timeout)

    result = probe_codex_health(codex_path="codex", model="gpt-5.6-sol", timeout=3)

    assert (result.state, result.error_class) == ("unknown", "timeout")
