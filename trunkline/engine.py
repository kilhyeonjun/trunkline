"""Limit detection + auto-switch decisions. Pure state machine, zero I/O —
the daemon owns side effects (Mobius AutoSwitchEngine port, design §4.5)."""
from __future__ import annotations

import json
from dataclasses import dataclass

SHORT_WINDOW_MAX_MINUTES = 1440   # window_minutes < 1440 → 단기(5h류) 창
COOLDOWN_S = 120.0
RETURN_GRACE_S = 60.0


@dataclass(frozen=True)
class RateLimitEvent:
    used_percent: float
    window_minutes: int | None
    resets_at: int | None
    limit_name: str | None


@dataclass(frozen=True)
class Decision:
    kind: str            # "none" | "fallback" | "return"
    target: str | None
    reason: str


NONE = Decision(kind="none", target=None, reason="")


def parse_token_count(line: str) -> list[RateLimitEvent]:
    try:
        obj = json.loads(line)
    except Exception:
        return []
    payload = obj.get("payload") or {}
    if payload.get("type") != "token_count":
        return []
    # rate_limits는 payload.info 내부가 아니라 형제 키 (2026-07-20 실측, 리뷰 minor)
    rl = payload.get("rate_limits") or {}
    limit_name = rl.get("limit_name")
    events = []
    for key in ("primary", "secondary"):
        win = rl.get(key)
        if not isinstance(win, dict):
            continue
        events.append(RateLimitEvent(
            used_percent=float(win.get("used_percent") or 0.0),
            window_minutes=win.get("window_minutes"),
            resets_at=win.get("resets_at"),
            limit_name=str(limit_name) if limit_name else None,
        ))
    return events


def is_account_exhausting(ev: RateLimitEvent) -> bool:
    if ev.limit_name is not None:
        return False  # 모델 전용 한도 — 계정 소진 아님
    return ev.used_percent >= 100.0


class AutoSwitchEngine:
    def __init__(self, priority: list[str], cooldown_s: float = COOLDOWN_S):
        self.priority = priority
        self.cooldown_s = cooldown_s
        self._last_switch_at: float | None = None  # 메모리 전용 (리뷰 minor)

    def note_switch(self, now: float) -> None:
        self._last_switch_at = now

    def _in_cooldown(self, now: float) -> bool:
        return (self._last_switch_at is not None
                and now - self._last_switch_at < self.cooldown_s)

    def on_exhausted(self, active: str, now: float) -> Decision:
        if self._in_cooldown(now):
            return NONE
        try:
            idx = self.priority.index(active)
        except ValueError:
            return NONE
        if idx + 1 >= len(self.priority):
            return NONE  # 마지막 계정 — 폴백 대상 없음
        return Decision(kind="fallback", target=self.priority[idx + 1],
                        reason=f"{active} exhausted")

    def on_tick(self, active: str, now: float, primary_label: str,
                primary_reset_at: float | None, auto_switched: bool) -> Decision:
        if not auto_switched or active == primary_label:
            return NONE
        if primary_reset_at is None or now < primary_reset_at + RETURN_GRACE_S:
            return NONE
        if self._in_cooldown(now):
            return NONE
        return Decision(kind="return", target=primary_label, reason="primary reset")
