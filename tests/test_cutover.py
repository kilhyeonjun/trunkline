import json
from pathlib import Path

from trunkline.cutover import run_cutover


def _auth(acct: str) -> bytes:
    return json.dumps({"tokens": {"account_id": acct}}).encode()


def test_cutover_boots_out_before_touching_auth(codex_home, tmp_path, monkeypatch):
    """순서 검증: bootout이 auth.json 조작보다 먼저다 (리뷰 C-4)."""
    calls = []
    store = codex_home / "accounts" / "personal"
    store.mkdir(parents=True)
    (store / "auth.json").write_bytes(_auth("acct-p"))
    live = codex_home / "auth.json"
    live.symlink_to(store / "auth.json")

    def fake_launchctl(cmd):
        calls.append(("launchctl", live.is_symlink()))
        return 0

    log = run_cutover(codex_home, launchctl=fake_launchctl, uid=501, home=tmp_path)

    assert calls[0] == ("launchctl", True)      # bootout 시점에 심링크 아직 존재
    assert not live.is_symlink()                 # 이후 실파일 전환
    assert live.read_bytes() == _auth("acct-p")
    assert (store / "auth.json").read_bytes() == _auth("acct-p")  # 원본 보존
    assert any("bootout" in l for l in log)


def test_cutover_idempotent_when_no_symlink(codex_home, tmp_path):
    (codex_home / "auth.json").write_bytes(_auth("acct-p"))
    log = run_cutover(codex_home, launchctl=lambda cmd: 0, uid=501, home=tmp_path)
    assert (codex_home / "auth.json").read_bytes() == _auth("acct-p")
    assert any("already a regular file" in l for l in log)


def test_cutover_missing_auth_ok(codex_home, tmp_path):
    log = run_cutover(codex_home, launchctl=lambda cmd: 0, uid=501, home=tmp_path)
    assert any("no live auth" in l for l in log)


def test_cutover_renames_legacy_plist_only_in_given_home(codex_home, tmp_path):
    la = tmp_path / "Library" / "LaunchAgents"
    la.mkdir(parents=True)
    legacy = la / "com.kilhyeonjun.codex-account-auto.plist"
    legacy.write_text("<plist/>")
    log = run_cutover(codex_home, launchctl=lambda cmd: 0, uid=501, home=tmp_path)
    assert not legacy.exists()
    assert (la / "com.kilhyeonjun.codex-account-auto.plist.disabled").exists()
    assert any("renamed" in l for l in log)
