import json
from pathlib import Path

import pytest

from trunkline.daemon import Daemon
from trunkline.providerio import CodexConfigIO
from trunkline.store import Account, AccountStore, StoreData
from trunkline.switcher import Switcher

from conftest import _cfg, _creds


def _auth(acct: str) -> bytes:
    return json.dumps({"tokens": {"account_id": acct}}).encode()


def _exhaust_line(used=100.0, window=300, limit_name=None) -> str:
    return json.dumps({"payload": {"type": "token_count", "rate_limits": {
        "limit_name": limit_name,
        "primary": {"used_percent": used, "window_minutes": window,
                    "resets_at": 1785060000}}}})


def _two_window_line(primary_resets_at, secondary_resets_at,
                      primary_used=50.0, limit_name=None) -> str:
    return json.dumps({"payload": {"type": "token_count", "rate_limits": {
        "limit_name": limit_name,
        "primary": {"used_percent": primary_used, "window_minutes": 300,
                    "resets_at": primary_resets_at},
        "secondary": {"used_percent": 10.0, "window_minutes": 10080,
                      "resets_at": secondary_resets_at}}}})


def _health_line(provider="codex", label="personal", model="gpt-5.6-sol",
                 status=400, message=None, observed_at=1) -> str:
    return json.dumps({
        "type": "account_health", "provider": provider, "label": label,
        "model": model, "status": status,
        "message": message or (
            "The 'gpt-5.6-sol' model is not supported when using Codex "
            "with a ChatGPT account."
        ),
        "observed_at": observed_at,
        "account_id": "must-not-persist", "secret": "must-not-persist",
    })


@pytest.fixture
def env(sb_root, codex_home, tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    store = AccountStore(root=sb_root, codex_home=codex_home)
    io = CodexConfigIO(codex_home)
    sw = Switcher(store, {"codex": io})
    store.save(StoreData(
        accounts=[Account("personal", "codex"), Account("company", "codex")],
        active_by_provider={"codex": "personal"},
        mode_by_provider={"codex": "auto"},
        auto_switched={"codex": False}, preferred={},
    ))
    for label, acct in [("personal", "acct-p"), ("company", "acct-c")]:
        p = store.secret_path(Account(label, "codex"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_auth(acct))
    (codex_home / "auth.json").write_bytes(_auth("acct-p"))
    d = Daemon(store, sw, io, sessions_dir=sessions,
               claude_json=tmp_path / "no-claude.json", claude_creds=tmp_path / "no-creds.json")
    return d, store, io, sessions


@pytest.fixture
def claude_env(sb_root, codex_home, tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    store = AccountStore(root=sb_root, codex_home=codex_home)
    io = CodexConfigIO(codex_home)
    sw = Switcher(store, {"codex": io})
    store.save(StoreData(
        accounts=[Account("personal", "codex"), Account("company", "codex")],
        active_by_provider={"codex": "personal"},
        mode_by_provider={"codex": "auto"},
        auto_switched={"codex": False}, preferred={},
    ))
    for label, acct in [("personal", "acct-p"), ("company", "acct-c")]:
        p = store.secret_path(Account(label, "codex"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_auth(acct))
    (codex_home / "auth.json").write_bytes(_auth("acct-p"))
    claude_json = _cfg(tmp_path)
    claude_creds = _creds(tmp_path)
    d = Daemon(store, sw, io, sessions_dir=sessions,
               claude_json=claude_json, claude_creds=claude_creds)
    return d, store, io, sessions, claude_json, claude_creds


def test_first_tick_seeds_without_switching(env):
    d, store, io, sessions = env
    (sessions / "s1.jsonl").write_text(_exhaust_line() + "\n")  # 과거 이벤트
    d.tick(now=0.0)
    assert store.load().active_by_provider["codex"] == "personal"  # 오탐 없음


def test_exhaustion_appended_after_seed_triggers_fallback(env):
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)                                   # seed
    f.write_text(_exhaust_line() + "\n")              # 새 append
    d.tick(now=10.0)
    assert store.load().active_by_provider["codex"] == "company"
    assert store.load().auto_switched["codex"] is True
    assert (io.codex_home / "auth.json").read_bytes() == _auth("acct-c")


def test_model_limit_does_not_switch(env):
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_exhaust_line(limit_name="gpt-5-pro") + "\n")
    d.tick(now=10.0)
    assert store.load().active_by_provider["codex"] == "personal"


def test_lock_mode_never_switches(env):
    d, store, io, sessions = env
    data = store.load()
    data.mode_by_provider["codex"] = "lock"
    store.save(data)
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_exhaust_line() + "\n")
    d.tick(now=10.0)
    assert store.load().active_by_provider["codex"] == "personal"


def test_entitlement_event_persists_redacted_health_and_auto_switches_once(env):
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_health_line() + "\n")
    d.tick(now=10.0)

    state = json.loads(store.state_path.read_text())["providers"]["codex"]
    assert store.load().active_by_provider["codex"] == "company"
    assert state["account_health"] == [{
        "label": "personal", "model": "gpt-5.6-sol",
        "state": "entitlement_unavailable", "observed_at": 1,
        "reset_at": None, "error_class": None,
    }]


def test_entitlement_event_in_lock_mode_is_persisted_but_never_switches(env):
    d, store, io, sessions = env
    data = store.load()
    data.mode_by_provider["codex"] = "lock"
    store.save(data)
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_health_line() + "\n")
    d.tick(now=10.0)

    assert store.load().active_by_provider["codex"] == "personal"
    assert json.loads(store.state_path.read_text())["providers"]["codex"]["account_health"]


def test_transient_or_unknown_health_never_persists_or_switches(env):
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_health_line(status=503, message="Too many concurrent requests") + "\n")
    d.tick(now=10.0)

    state = json.loads(store.state_path.read_text())["providers"]["codex"]
    assert store.load().active_by_provider["codex"] == "personal"
    assert state["account_health"] == []


def test_state_json_published(env):
    d, store, io, sessions = env
    d.tick(now=0.0)
    state = json.loads((store.state_path).read_text())
    assert state["providers"]["codex"]["active"] == "personal"
    assert state["providers"]["codex"]["mode"] == "auto"


def test_cooldown_survives_engine_recreation(env):
    """계정 추가로 엔진이 재생성돼도 쿨다운 유지 — 연쇄 전환 차단."""
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    f.write_text(_exhaust_line() + "\n")
    d.tick(now=10.0)     # personal -> company 폴백, 쿨다운 시작
    assert store.load().active_by_provider["codex"] == "company"
    # 계정 추가 -> priority 변경 -> 엔진 재생성
    from trunkline.store import Account
    data = store.load()
    data.accounts.append(Account("third", "codex"))
    store.save(data)
    p = store.secret_path(Account("third", "codex"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_auth("acct-t"))
    # 새(비격리) 파일에서 즉시 소진 이벤트 — 쿨다운 내이므로 전환 금지
    f2 = sessions / "s2.jsonl"
    f2.write_text(_exhaust_line() + "\n")
    d.tick(now=20.0)
    assert store.load().active_by_provider["codex"] == "company"   # 연쇄 전환 없음


def test_reconcile_change_republishes_state(env):
    import json as _json
    d, store, io, sessions = env
    d.tick(now=0.0)   # seed + 초기 state 발행
    # 외부(수동) 전환 시뮬레이션: 라이브를 company 바이트로
    io.write_live_secret(_auth("acct-c"))
    d.tick(now=16.0)  # reconcile_s(15s) 경과 -> reconcile -> 재발행
    state = _json.loads(store.state_path.read_text())
    assert state["providers"]["codex"]["active"] == "company"


def test_primary_reset_at_ignores_secondary_window(env):
    """5h(primary)와 7d(secondary) 창이 같은 이벤트에 섞여 와도 primary_reset_at은
    5h(단기) 값만 기록해야 한다 — 7d 값이 덮어쓰면 복귀 판단(on_tick)이 틀어진다."""
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)   # seed
    f.write_text(_two_window_line(primary_resets_at=1000000, secondary_resets_at=2000000) + "\n")
    d.tick(now=10.0)
    assert store.load().primary_reset_at["codex"] == 1000000.0


def _session_line(used_percent=42.0, window_minutes=300, resets_at=2000,
                   limit_name=None) -> str:
    return json.dumps({"payload": {"type": "token_count", "rate_limits": {
        "limit_name": limit_name,
        "primary": {"used_percent": used_percent, "window_minutes": window_minutes,
                    "resets_at": resets_at}}}})


def test_publish_every_tick_even_without_change(env):
    """변경 없어도 매 tick 발행 — updated_at 전진 (heartbeat)."""
    d, store, io, sessions = env
    d.tick(1000.0)
    d.tick(1003.0)
    st = json.loads(store.state_path.read_text())
    assert st["version"] == 2
    assert st["updated_at"] == 1003.0


def test_publish_on_empty_labels(env):
    """스토어 비정상(빈 accounts)에도 heartbeat + accounts:[] 발행."""
    d, store, io, sessions = env
    d.tick(1000.0)
    store.save(StoreData(accounts=[], active_by_provider={}, mode_by_provider={},
                         auto_switched={}, preferred={}))
    d.tick(1003.0)
    st = json.loads(store.state_path.read_text())
    assert st["updated_at"] == 1003.0
    assert st["providers"]["codex"]["accounts"] == []


def test_v2_schema_fields(env):
    d, store, io, sessions = env
    d.tick(1000.0)
    d.tick(1003.0)
    p = json.loads(store.state_path.read_text())["providers"]["codex"]
    assert set(p) == {"active", "mode", "accounts", "observed", "last_event", "account_health"}
    assert all(set(a) == {"label", "snapshot_ok"} for a in p["accounts"])


def test_observed_from_short_window_only(env):
    """short window(<1440)·limit_name 없음만 observed로. 장기창·모델한도 제외."""
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(1000.0)
    f.write_text(_session_line(used_percent=42.0, window_minutes=300, resets_at=2000) + "\n")
    d.tick(1003.0)
    obs = json.loads(store.state_path.read_text())["providers"]["codex"]["observed"]
    assert obs == {"used_percent": 42.0, "resets_at": 2000.0, "at": 1003.0}
    with open(f, "a") as fh:
        fh.write(_session_line(used_percent=90.0, window_minutes=10080, resets_at=3000) + "\n")
    d.tick(1006.0)
    obs = json.loads(store.state_path.read_text())["providers"]["codex"]["observed"]
    assert obs["used_percent"] == 42.0  # 장기창은 무시 — 갱신 안 됨


def test_observed_cleared_and_quarantined_on_external_switch(env):
    """tick 사이 활성 라벨 변경(수동 CLI/메뉴) → observed 초기화 + quarantine_seen."""
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(1000.0)
    f.write_text(_session_line(used_percent=95.0, window_minutes=300, resets_at=2000) + "\n")
    d.tick(1003.0)
    data = store.load()
    data.active_by_provider["codex"] = "company"   # 외부 전환 시뮬레이션
    store.save(data)
    called = []
    d.router.quarantine_seen = lambda: called.append(1)
    d.tick(1006.0)
    st = json.loads(store.state_path.read_text())["providers"]["codex"]
    assert st["observed"] is None
    assert called == [1]


def test_batch_break_after_fallback(env):
    """auto fallback 결정 후 같은 배치 잔여 라인 소비 중단 — 새 활성 오귀속 방지."""
    d, store, io, sessions = env
    data = store.load()
    data.mode_by_provider["codex"] = "auto"
    store.save(data)
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(1000.0)
    lines = [
        _session_line(used_percent=100.0, window_minutes=300, resets_at=2000),  # 소진 → fallback
        _session_line(used_percent=99.0, window_minutes=300, resets_at=2000),   # 구 계정 잔여 라인
    ]
    f.write_text("\n".join(lines) + "\n")
    d.tick(1003.0)
    st = json.loads(store.state_path.read_text())["providers"]["codex"]
    assert st["last_event"]["type"] == "fallback"
    assert st["last_event"]["reason"]           # Decision.reason 포함
    assert st["observed"] is None               # fallback 시 초기화, 잔여 99% 미귀속


def test_primary_reset_persisted_across_restart(env):
    d, store, io, sessions = env
    f = sessions / "s1.jsonl"
    f.write_text("")
    d.tick(now=0.0)
    # primary 사용 중 reset 시각 관측 (미소진 이벤트)
    f.write_text(_exhaust_line(used=50.0) + "\n")
    d.tick(now=5.0)
    assert store.load().primary_reset_at["codex"] == 1785060000.0
    # 소진 -> 폴백
    with open(f, "a") as fh:
        fh.write(_exhaust_line() + "\n")
    d.tick(now=10.0)
    assert store.load().active_by_provider["codex"] == "company"
    # 데몬 재시작 (새 인스턴스) — primary 로그 없이도 리셋 후 복귀 가능해야 함
    from trunkline.daemon import Daemon
    from trunkline.switcher import Switcher
    from trunkline.providerio import CodexConfigIO
    d2 = Daemon(store, Switcher(store, {"codex": io}), io, sessions_dir=sessions,
                claude_json=sessions / "no-claude.json",
                claude_creds=sessions / "no-creds.json")
    d2.tick(now=1785060000.0)          # seed only
    d2.tick(now=1785060000.0 + 200.0)  # reset+60s 지남 -> 복귀
    assert store.load().active_by_provider["codex"] == "personal"


def test_publishes_claude_entry(claude_env):
    d, store, io, sessions, claude_json, claude_creds = claude_env
    d.tick(now=0.0)
    state = json.loads(store.state_path.read_text())
    assert state["providers"]["claude"] == {
        "login_ok": True, "login_warning": None,
        "usage": {"seven_day_pct": 12.0, "resets_at": 1_784_584_800.304197, "at": 1_784_511_168.429},
    }


def test_claude_whitelist_keys(claude_env):
    d, store, io, sessions, claude_json, claude_creds = claude_env
    d.tick(now=0.0)
    claude = json.loads(store.state_path.read_text())["providers"]["claude"]
    assert set(claude) == {"login_ok", "login_warning", "usage"}
    usage = claude["usage"]
    assert set(usage) == {"seven_day_pct", "resets_at", "at"}
    for v in usage.values():
        assert isinstance(v, float) or v is None
    assert isinstance(claude["login_ok"], bool)
    assert claude["login_warning"] is None or isinstance(claude["login_warning"], str)


def test_claude_omitted_when_unknown(claude_env):
    d, store, io, sessions, claude_json, claude_creds = claude_env
    claude_creds.unlink()
    d.tick(now=0.0)
    state = json.loads(store.state_path.read_text())
    assert "claude" not in state["providers"]


def test_claude_usage_null_when_pct_none(claude_env):
    d, store, io, sessions, claude_json, claude_creds = claude_env
    claude_json.write_text(json.dumps(json.loads(claude_json.read_text()) | {
        "cachedUsageUtilization": {
            "fetchedAtMs": 1_784_511_168_429,
            "utilization": {
                "five_hour": {"utilization": 0, "resets_at": "2026-07-20T22:00:00.304197+00:00"},
                "seven_day": {"utilization": None, "resets_at": "2026-07-20T22:00:00.304197+00:00"},
            },
        },
    }))
    d.tick(now=0.0)
    claude = json.loads(store.state_path.read_text())["providers"]["claude"]
    assert claude["usage"] is None


def test_claude_reader_exception_does_not_block_codex_publish(env, tmp_path):
    """claude 파일이 dict가 아닌 JSON(예: 리스트)이어도 codex 발행은 계속."""
    d, store, io, sessions = env
    bad = tmp_path / "claude.json"
    bad.write_text("[1,2,3]")  # cfg.get에서 AttributeError 유발
    d.claude_json = bad
    creds = tmp_path / "creds.json"
    creds.write_text('{"claudeAiOauth":{"refreshTokenExpiresAt":1785300106975}}')
    d.claude_creds = creds
    d.tick(1000.0)
    d.tick(1003.0)
    st = json.loads(store.state_path.read_text())
    assert st["updated_at"] == 1003.0                       # codex heartbeat 생존
    assert "claude" not in st["providers"]                  # claude 키 생략


def test_no_egress_symbols_in_daemon_scope():
    root = Path(__file__).parent.parent / "trunkline"
    src = (root / "daemon.py").read_text() + (root / "claude_status.py").read_text()
    for banned in ("urllib", "urlopen", "http.client", "socket", "subprocess", "os.system"):
        assert banned not in src, banned
