import base64
import json
from pathlib import Path

import pytest

from trunkline import cli
from trunkline.claude_status import ClaudeStatus
from trunkline.store import AccountStore


def _auth(acct: str) -> bytes:
    return json.dumps({"tokens": {"account_id": acct}}).encode()


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.x"


def _auth_with_plan(acct: str, plan: str) -> bytes:
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": acct, "chatgpt_plan_type": plan}}
    return json.dumps({"tokens": {"account_id": acct, "access_token": _jwt(claims)}}).encode()


@pytest.fixture
def env(sb_root, codex_home, tmp_path, monkeypatch):
    for label, acct in [("personal", "acct-p"), ("company", "acct-c")]:
        d = codex_home / "accounts" / label
        d.mkdir(parents=True)
        (d / "auth.json").write_bytes(_auth(acct))
    (codex_home / "auth.json").write_bytes(_auth("acct-p"))
    monkeypatch.setattr(cli, "SB_ROOT", sb_root)
    monkeypatch.setattr(cli, "CODEX_HOME", codex_home)
    # 실제 홈 디렉터리 절대 미접근 — 존재하지 않는 tmp 경로로 고정 (기본 ok=False)
    monkeypatch.setattr(cli, "CLAUDE_JSON", tmp_path / "no-claude.json")
    monkeypatch.setattr(cli, "CLAUDE_CREDS", tmp_path / "no-creds.json")
    return sb_root, codex_home


def test_init_discovers_accounts(env, capsys):
    sb_root, codex_home = env
    assert cli.main(["init", "--priority", "personal,company"]) == 0
    store = AccountStore(root=sb_root, codex_home=codex_home)
    data = store.load()
    assert [a.label for a in data.accounts] == ["personal", "company"]
    assert data.mode_by_provider["codex"] == "lock"   # 안전 기본값


def test_status_shows_active(env, capsys):
    cli.main(["init", "--priority", "personal,company"])
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "personal" in out and "lock" in out


def test_status_missing_snapshot_shown_in_korean(env, sb_root, codex_home, capsys):
    """W — 스냅샷 없는 계정은 영문 'missing snapshot'이 아니라 한국어 '스냅샷 없음'으로 표기."""
    from trunkline.store import Account, AccountStore, StoreData
    store = AccountStore(root=sb_root, codex_home=codex_home)
    store.save(StoreData(
        accounts=[Account("personal", "codex"), Account("ghost", "codex")],
        active_by_provider={}, mode_by_provider={"codex": "lock"},
        auto_switched={"codex": False}, preferred={},
    ))
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "스냅샷 없음" in out
    assert "missing snapshot" not in out


def test_switch(env):
    sb_root, codex_home = env
    cli.main(["init", "--priority", "personal,company"])
    assert cli.main(["switch", "company"]) == 0
    assert (codex_home / "auth.json").read_bytes() == _auth("acct-c")


def test_switch_prints_korean_confirmation(env, capsys):
    """W — 'switched to X' 영문 대신 'X로 전환됨' 한국어 출력."""
    cli.main(["init", "--priority", "personal,company"])
    capsys.readouterr()
    assert cli.main(["switch", "company"]) == 0
    out = capsys.readouterr().out
    assert "company로 전환됨 (새 codex 세션부터 적용)" in out
    assert "switched to" not in out


def test_init_priority_dedups_duplicate_labels(env, sb_root, codex_home):
    """P — --priority에 중복 label(a,a)이 와도 store에 중복 저장되지 않음(usage 행 크래시 방어)."""
    assert cli.main(["init", "--priority", "personal,personal,company"]) == 0
    store = AccountStore(root=sb_root, codex_home=codex_home)
    data = store.load()
    assert [a.label for a in data.accounts] == ["personal", "company"]


def test_auto_and_lock_modes(env):
    sb_root, codex_home = env
    cli.main(["init", "--priority", "personal,company"])
    cli.main(["auto"])
    store = AccountStore(root=sb_root, codex_home=codex_home)
    assert store.load().mode_by_provider["codex"] == "auto"
    cli.main(["lock", "personal"])
    assert store.load().mode_by_provider["codex"] == "lock"


def test_unknown_switch_returns_1(env, capsys):
    cli.main(["init", "--priority", "personal,company"])
    assert cli.main(["switch", "nope"]) == 1


def test_usage_json_outputs_rows(env, monkeypatch, capsys):
    sb_root, codex_home = env
    cli.main(["init", "--priority", "personal,company"])
    # Monkeypatch read_usage to return deterministic rows
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=12.5, primary_reset=None,
        secondary_used=3.0, secondary_reset=None, error=None))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()  # Clear init output
    rc = cli.main(["usage", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    rows = json.loads(out)["codex"]
    assert [r["label"] for r in rows] == ["personal", "company"]
    assert rows[0]["primary_used"] == 12.5


def test_usage_human_output_unchanged(env, monkeypatch, capsys):
    sb_root, codex_home = env
    cli.main(["init", "--priority", "personal,company"])
    # Monkeypatch read_usage to return deterministic rows (실측 wham: primary=7d 창)
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=12.5, primary_reset=None,
        secondary_used=3.0, secondary_reset=None, error=None,
        primary_window_minutes=10080, secondary_window_minutes=300))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()  # Clear init output
    rc = cli.main(["usage"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "personal: 7d 12.5% · 5h 3%" in out
    assert "company: 7d 12.5% · 5h 3%" in out


def test_window_label_mapping(env, monkeypatch, capsys):
    """_window_label: 300→5h, 10080→7d, None→항목 생략, 그 외 분 단위 파생."""
    sb_root, codex_home = env
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    rows_by_label = {
        "personal": UsageRow(label="personal", ok=True, stale=False,
                              primary_used=1.0, primary_reset=None,
                              secondary_used=2.0, secondary_reset=None, error=None,
                              primary_window_minutes=300, secondary_window_minutes=10080),
        "company": UsageRow(label="company", ok=True, stale=False,
                             primary_used=3.0, primary_reset=None,
                             secondary_used=None, secondary_reset=None, error=None,
                             primary_window_minutes=None, secondary_window_minutes=None),
    }
    monkeypatch.setattr(cli, "read_usage", lambda label, path: rows_by_label[label])
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()
    rc = cli.main(["usage"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "personal: 5h 1% · 7d 2%" in out
    # window_minutes=None → 창 항목 생략 (라벨 없이 값만, 구분자 없음)
    assert "company: 3%" in out


def test_window_label_derived_hours_and_days():
    """창 라벨 케이스(분 단위 입력): 300/10080/None/45/120/1440/2880/4320.
    U — GaugeSpec.windowTitle과 동기: 케이스 표 변경 시 양쪽(여기 ↔ GaugeSpecTests.swift) 동시 갱신."""
    from trunkline.cli import _window_label
    assert _window_label(300) == "5h"
    assert _window_label(10080) == "7d"
    assert _window_label(None) is None
    assert _window_label(45) == "45m"    # 60분 미만 → 분 단위(U)
    assert _window_label(120) == "2h"
    assert _window_label(86400 // 60) == "24h"   # 1440min < 2880 → 시간 단위
    assert _window_label(2880) == "2d"
    assert _window_label(4320) == "3d"


def _claude_ok(**overrides) -> ClaudeStatus:
    base = dict(ok=True, email="h@x.net", tier="max_20x", five_hour_pct=0.0,
                five_hour_resets_at=1_784_584_800.0, seven_day_pct=12.0,
                seven_day_resets_at=1_784_584_800.0, fetched_at=1_784_511_168.429,
                login_expires_at=1_785_300_106.975, error=None)
    base.update(overrides)
    return ClaudeStatus(**base)


def test_status_shows_claude_line(env, monkeypatch, capsys):
    cli.main(["init", "--priority", "personal,company"])
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    monkeypatch.setattr(cli.time, "time", lambda: 1_784_511_168.0)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "claude: h@x.net (max_20x) · 로그인 OK" in out


def test_status_claude_warning(env, monkeypatch, capsys):
    cli.main(["init", "--priority", "personal,company"])
    expired = _claude_ok(login_expires_at=0.0)
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: expired)
    monkeypatch.setattr(cli.time, "time", lambda: 1_784_600_000.0)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "· ⚠️ 재로그인 필요: claude auth login" in out


def test_status_claude_unknown(env, monkeypatch, capsys):
    cli.main(["init", "--priority", "personal,company"])
    unknown = ClaudeStatus(ok=False, email=None, tier=None, five_hour_pct=None,
                            five_hour_resets_at=None, seven_day_pct=None,
                            seven_day_resets_at=None, fetched_at=None,
                            login_expires_at=None, error="cache_missing")
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: unknown)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "claude: 상태 불명 (cache_missing)" in out


def test_usage_json_nested(env, monkeypatch, capsys):
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=12.5, primary_reset=None,
        secondary_used=3.0, secondary_reset=None, error=None))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()
    rc = cli.main(["usage", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"codex", "claude"}
    assert [r["label"] for r in out["codex"]] == ["personal", "company"]
    assert out["claude"]["seven_day_pct"] == 12.0


def test_usage_json_includes_plan_from_identity(env, monkeypatch, capsys):
    """계정별 auth.json의 chatgpt_plan_type → usage --json codex 행 plan (T6b)."""
    sb_root, codex_home = env
    (codex_home / "accounts" / "personal" / "auth.json").write_bytes(_auth_with_plan("acct-p", "pro"))
    (codex_home / "accounts" / "company" / "auth.json").write_bytes(_auth_with_plan("acct-c", "plus"))
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=12.5, primary_reset=None,
        secondary_used=3.0, secondary_reset=None, error=None))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()
    rc = cli.main(["usage", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)["codex"]
    assert {r["label"]: r["plan"] for r in rows} == {"personal": "pro", "company": "plus"}


def test_usage_plan_none_when_identity_unreadable(env, monkeypatch, capsys):
    """auth.json 손상/미존재 등 identity 읽기 실패 → plan None (크래시 금지)."""
    sb_root, codex_home = env
    (codex_home / "accounts" / "personal" / "auth.json").write_bytes(b"not json")
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=1.0, primary_reset=None,
        secondary_used=None, secondary_reset=None, error=None))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()
    rc = cli.main(["usage", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)["codex"]
    assert rows[0]["plan"] is None


def test_usage_human_output_shows_plan(env, monkeypatch, capsys):
    """사람용 usage 출력 병기: `personal (pro): 7d 41%` 형태."""
    sb_root, codex_home = env
    (codex_home / "accounts" / "personal" / "auth.json").write_bytes(_auth_with_plan("acct-p", "pro"))
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=41.0, primary_reset=None,
        secondary_used=None, secondary_reset=None, error=None,
        primary_window_minutes=10080))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    capsys.readouterr()
    rc = cli.main(["usage"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "personal (pro): 7d 41%" in out
    # plan 없음(company)은 괄호 생략 — 기존 라벨 그대로
    assert "company: 7d" in out and "company (" not in out


def test_usage_human_claude_line(env, monkeypatch, capsys):
    cli.main(["init", "--priority", "personal,company"])
    from trunkline.usage import UsageRow
    monkeypatch.setattr(cli, "read_usage", lambda label, path: UsageRow(
        label=label, ok=True, stale=False, primary_used=12.5, primary_reset=None,
        secondary_used=3.0, secondary_reset=None, error=None))
    monkeypatch.setattr(cli, "read_claude_status", lambda *_: _claude_ok())
    monkeypatch.setattr(cli.time, "time", lambda: 1_784_600_000.0)
    capsys.readouterr()
    rc = cli.main(["usage"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "claude: 5h 0% · 7d 12%" in out
    assert "전 기준" in out
