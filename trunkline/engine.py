"""Limit detection + auto-switch decisions. Pure state machine, zero I/O —
the daemon owns side effects (Mobius AutoSwitchEngine port, design §4.5)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

SHORT_WINDOW_MAX_MINUTES = 1440   # window_minutes < 1440 → 단기(5h류) 창
COOLDOWN_S = 120.0
RETURN_GRACE_S = 60.0
ENTITLEMENT_MESSAGE = re.compile(
    r"^the (?:(?P<quote>['\"])[^'\"]+(?P=quote) )?model is not supported "
    r"when using codex with a chatgpt account\.?$"
)
SELECTABLE_SUCCESSOR_STATES = {None, "healthy", "unknown"}
HEALTH_STATES = {
    "healthy",
    "usage_exhausted",
    "entitlement_unavailable",
    "auth_stale",
    "temporarily_throttled",
    "unknown",
}


@dataclass(frozen=True)
class RateLimitEvent:
    used_percent: float
    window_minutes: int | None
    resets_at: int | None
    limit_name: str | None


@dataclass(frozen=True)
class AccountHealthEvent:
    provider: str
    label: str
    model: str
    state: str
    observed_at: int
    reset_at: int | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class Decision:
    kind: str            # "none" | "fallback" | "return"
    target: str | None
    reason: str


NONE = Decision(kind="none", target=None, reason="")


def parse_account_health(line: str) -> list[AccountHealthEvent]:
    try:
        obj = json.loads(line)
    except Exception:
        return []
    if not isinstance(obj, dict) or obj.get("type") != "account_health":
        return []

    provider = obj.get("provider")
    label = obj.get("label")
    model = obj.get("model")
    observed_at = obj.get("observed_at")
    if (
        not isinstance(provider, str)
        or not provider.strip()
        or not isinstance(label, str)
        or not label.strip()
        or not isinstance(model, str)
        or not model.strip()
        or isinstance(observed_at, bool)
        or not isinstance(observed_at, int)
    ):
        return []
    reset_at = obj.get("reset_at")
    error_class = obj.get("error_class")
    if (
        reset_at is not None
        and (isinstance(reset_at, bool) or not isinstance(reset_at, int))
        or (error_class is not None and not isinstance(error_class, str))
    ):
        return []

    status = obj.get("status")
    message = obj.get("message")
    is_entitlement_unavailable = (
        status == 400
        and isinstance(message, str)
        and ENTITLEMENT_MESSAGE.fullmatch(" ".join(message.casefold().split())) is not None
    )
    return [AccountHealthEvent(
        provider=provider,
        label=label,
        model=model,
        state="entitlement_unavailable" if is_entitlement_unavailable else "unknown",
        observed_at=observed_at,
        reset_at=reset_at,
        error_class=error_class,
    )]


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

    def on_unavailable(self, provider: str, active: str, model: str, now: float,
                       health: dict[tuple[str, str, str], str]) -> Decision:
        if not provider or not active or not model:
            return NONE
        if self._in_cooldown(now):
            return NONE
        if health.get((provider, active, model)) != "entitlement_unavailable":
            return NONE
        try:
            idx = self.priority.index(active)
        except ValueError:
            return NONE
        for candidate in self.priority[idx + 1:]:
            if health.get((provider, candidate, model)) not in SELECTABLE_SUCCESSOR_STATES:
                continue
            return Decision(
                kind="fallback",
                target=candidate,
                reason=f"{active} unavailable for {model}",
            )
        return NONE

    def on_tick(self, active: str, now: float, primary_label: str,
                primary_reset_at: float | None, auto_switched: bool) -> Decision:
        if not auto_switched or active == primary_label:
            return NONE
        if primary_reset_at is None or now < primary_reset_at + RETURN_GRACE_S:
            return NONE
        if self._in_cooldown(now):
            return NONE
        return Decision(kind="return", target=primary_label, reason="primary reset")
