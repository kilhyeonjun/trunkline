import json
from pathlib import Path

import pytest

from trunkline.engine import (
    AccountHealthEvent,
    AutoSwitchEngine,
    Decision,
    RateLimitEvent,
    parse_account_health,
    parse_token_count,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rollout-sample.jsonl"


def _lines():
    return FIXTURE.read_text().splitlines()


def test_exact_chatgpt_model_rejection_is_entitlement_unavailable():
    line = json.dumps({
        "type": "account_health",
        "provider": "codex",
        "label": "personal",
        "model": "gpt-5.6-sol",
        "status": 400,
        "message": (
            "The 'gpt-5.6-sol' model is not supported when using Codex "
            "with a ChatGPT account."
        ),
        "observed_at": 1,
    })

    assert parse_account_health(line)[0].state == "entitlement_unavailable"


def test_entitlement_message_normalizes_whitespace_before_matching():
    line = json.dumps({
        "type": "account_health",
        "provider": "codex",
        "label": "personal",
        "model": "gpt-5.6-sol",
        "status": 400,
        "message": (
            "The model  is not supported when using Codex\n"
            "with a ChatGPT account."
        ),
        "observed_at": 1,
    })

    assert parse_account_health(line)[0].state == "entitlement_unavailable"


@pytest.mark.parametrize(
    "status,message",
    [(400, "invalid request"), (503, "Too many concurrent requests")],
)
def test_ambiguous_or_transient_errors_are_not_persisted_as_entitlement(status, message):
    line = json.dumps({
        "type": "account_health",
        "provider": "codex",
        "label": "personal",
        "model": "gpt-5.6-sol",
        "status": status,
        "message": message,
        "observed_at": 1,
    })

    assert all(event.state != "entitlement_unavailable" for event in parse_account_health(line))


def test_account_health_event_preserves_optional_fields():
    line = json.dumps({
        "type": "account_health",
        "provider": "codex",
        "label": "personal",
        "model": "gpt-5.6-sol",
        "observed_at": 1,
        "reset_at": 2,
        "error_class": "provider_error",
    })

    assert parse_account_health(line) == [
        AccountHealthEvent(
            provider="codex",
            label="personal",
            model="gpt-5.6-sol",
            state="unknown",
            observed_at=1,
            reset_at=2,
            error_class="provider_error",
        )
    ]


@pytest.mark.parametrize("provider", [None, ""])
def test_account_health_requires_nonempty_provider(provider):
    payload = {
        "type": "account_health",
        "label": "personal",
        "model": "gpt-5.6-sol",
        "observed_at": 1,
    }
    if provider is not None:
        payload["provider"] = provider

    assert parse_account_health(json.dumps(payload)) == []


def test_unavailable_health_is_scoped_by_provider_label_and_model():
    engine = AutoSwitchEngine(priority=["personal", "company"])

    decision = engine.on_unavailable(
        provider="codex",
        active="personal",
        model="gpt-5.6-sol",
        now=1.0,
        health={
            ("other-provider", "personal", "gpt-5.6-sol"): "entitlement_unavailable",
        },
    )

    assert decision == Decision(kind="none", target=None, reason="")


def test_unavailable_model_falls_back_to_next_configured_account():
    engine = AutoSwitchEngine(priority=["personal", "company"])

    decision = engine.on_unavailable(
        provider="codex",
        active="personal",
        model="gpt-5.6-sol",
        now=1.0,
        health={("codex", "personal", "gpt-5.6-sol"): "entitlement_unavailable"},
    )

    assert decision == Decision(
        kind="fallback",
        target="company",
        reason="personal unavailable for gpt-5.6-sol",
    )


def test_unavailable_skips_successor_unavailable_for_the_same_model():
    engine = AutoSwitchEngine(priority=["personal", "company", "fallback"])

    decision = engine.on_unavailable(
        provider="codex",
        active="personal",
        model="gpt-5.6-sol",
        now=1.0,
        health={
            ("codex", "personal", "gpt-5.6-sol"): "entitlement_unavailable",
            ("codex", "company", "gpt-5.6-sol"): "entitlement_unavailable",
        },
    )

    assert decision == Decision(
        kind="fallback",
        target="fallback",
        reason="personal unavailable for gpt-5.6-sol",
    )


def test_unavailable_does_not_switch_for_ambiguous_model_input():
    engine = AutoSwitchEngine(priority=["personal", "company"])

    decision = engine.on_unavailable(
        provider="codex",
        active="personal",
        model="",
        now=1.0,
        health={("codex", "personal", ""): "entitlement_unavailable"},
    )

    assert decision == Decision(kind="none", target=None, reason="")


def test_unavailable_requires_entitlement_and_an_available_successor():
    engine = AutoSwitchEngine(priority=["personal", "company"])

    assert engine.on_unavailable(
        provider="codex",
        active="personal",
        model="gpt-5.6-sol",
        now=1.0,
        health={},
    ) == Decision(kind="none", target=None, reason="")
    assert engine.on_unavailable(
        provider="codex",
        active="company",
        model="gpt-5.6-sol",
        now=1.0,
        health={("codex", "company", "gpt-5.6-sol"): "entitlement_unavailable"},
    ) == Decision(kind="none", target=None, reason="")


def test_unavailable_respects_switch_cooldown():
    engine = AutoSwitchEngine(priority=["personal", "company"])
    engine.note_switch(now=1.0)

    assert engine.on_unavailable(
        provider="codex",
        active="personal",
        model="gpt-5.6-sol",
        now=2.0,
        health={("codex", "personal", "gpt-5.6-sol"): "entitlement_unavailable"},
    ) == Decision(kind="none", target=None, reason="")


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
