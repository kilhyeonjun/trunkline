from pathlib import Path

from trunkline.engine import AutoSwitchEngine, Decision, RateLimitEvent, parse_token_count

FIXTURE = Path(__file__).parent / "fixtures" / "rollout-sample.jsonl"


def _lines():
    return FIXTURE.read_text().splitlines()


def test_parse_extracts_primary_and_secondary():
    events = parse_token_count(_lines()[1])
    assert len(events) == 2
    primary = events[0]
    assert primary.used_percent == 100.0
    assert primary.window_minutes == 300
    assert primary.limit_name is None


def test_parse_model_specific_limit_flagged():
    events = parse_token_count(_lines()[2])
    assert events[0].limit_name == "gpt-5-pro"


def test_parse_non_token_count_returns_empty():
    assert parse_token_count(_lines()[3]) == []
    assert parse_token_count("not json") == []


def _exhausted(window_minutes=300):
    return RateLimitEvent(used_percent=100.0, window_minutes=window_minutes,
                          resets_at=1785060000, limit_name=None)


def is_account_exhausting(ev: RateLimitEvent) -> bool:
    from trunkline.engine import is_account_exhausting as f
    return f(ev)


def test_exhaustion_judgment_by_window_minutes():
    """슬롯 위치 아닌 window_minutes 판정 (Mobius 실측: 슬롯 이동)."""
    from trunkline.engine import is_account_exhausting
    assert is_account_exhausting(_exhausted(window_minutes=300))          # 5h 창 소진
    assert is_account_exhausting(_exhausted(window_minutes=10080))        # 7d 창 소진
    assert not is_account_exhausting(
        RateLimitEvent(used_percent=50.0, window_minutes=300, resets_at=None, limit_name=None))
    # 모델 전용 한도는 계정 판정 제외
    assert not is_account_exhausting(
        RateLimitEvent(used_percent=100.0, window_minutes=300, resets_at=None,
                       limit_name="gpt-5-pro"))


def test_fallback_to_next_in_priority():
    eng = AutoSwitchEngine(priority=["personal", "company"])
    d = eng.on_exhausted(active="personal", now=1000.0)
    assert d == Decision(kind="fallback", target="company", reason="personal exhausted")


def test_fallback_skips_during_cooldown():
    """120초 쿨다운: stale 로그 연쇄 전환(B→C→D) 차단."""
    eng = AutoSwitchEngine(priority=["personal", "company", "fallback"], cooldown_s=120.0)
    eng.note_switch(now=1000.0)
    assert eng.on_exhausted(active="company", now=1060.0).kind == "none"
    assert eng.on_exhausted(active="company", now=1121.0).kind == "fallback"


def test_no_fallback_when_last_account():
    eng = AutoSwitchEngine(priority=["personal", "company"])
    assert eng.on_exhausted(active="company", now=0.0).kind == "none"


def test_return_to_primary_after_reset_plus_60():
    eng = AutoSwitchEngine(priority=["personal", "company"])
    common = dict(active="company", primary_label="personal", auto_switched=True)
    assert eng.on_tick(now=1000.0, primary_reset_at=2000.0, **common).kind == "none"
    d = eng.on_tick(now=2061.0, primary_reset_at=2000.0, **common)
    assert d == Decision(kind="return", target="personal", reason="primary reset")


def test_no_return_for_manual_switch():
    """수동 전환은 안 되돌림 (auto_switched 플래그)."""
    eng = AutoSwitchEngine(priority=["personal", "company"])
    d = eng.on_tick(now=9999.0, active="company", primary_label="personal",
                    primary_reset_at=2000.0, auto_switched=False)
    assert d.kind == "none"
