"""Daemon: assembles router→parser→engine→switcher. Side effects live here;
engine stays pure. Gauges come from log events — the daemon makes NO network
calls (design §4.5)."""
from __future__ import annotations

import time
from pathlib import Path

from .claude_status import LIVE_JSON_DEFAULT, login_warning, read_claude_status
from .engine import (
    SHORT_WINDOW_MAX_MINUTES,
    AutoSwitchEngine,
    is_account_exhausting,
    parse_account_health,
    parse_token_count,
)
from .providerio import CodexConfigIO
from .router import SessionRouter
from .store import AccountStore
from .switcher import Switcher

PROVIDER = "codex"


class Daemon:
    def __init__(self, store: AccountStore, switcher: Switcher, io: CodexConfigIO,
                 sessions_dir: Path, poll_s: float = 3.0, reconcile_s: float = 15.0,
                 claude_json: Path | None = None, claude_creds: Path | None = None,
                 claude_live_json: Path | None = None):
        self.store = store
        self.switcher = switcher
        self.io = io
        self.sessions_dir = sessions_dir
        self.poll_s = poll_s
        self.reconcile_s = reconcile_s
        self.claude_json = claude_json or Path.home() / ".claude.json"
        self.claude_creds = claude_creds or Path.home() / ".claude" / ".credentials.json"
        self.claude_live_json = claude_live_json or LIVE_JSON_DEFAULT
        self.router = SessionRouter()
        self._seeded = False
        self._last_reconcile = 0.0
        self._last_event: dict | None = None
        self._last_observed: dict | None = None
        self._prev_active: str | None = None
        self._primary_reset_at: float | None = store.load().primary_reset_at.get(PROVIDER)

    def _session_files(self) -> list[Path]:
        return sorted(self.sessions_dir.rglob("*.jsonl"))

    def _engine(self, priority: list[str]) -> AutoSwitchEngine:
        eng = getattr(self, "_eng", None)
        if eng is None or eng.priority != priority:
            prev = eng._last_switch_at if eng is not None else None
            eng = self._eng = AutoSwitchEngine(priority)
            eng._last_switch_at = prev  # cooldown survives account-list changes
        return eng

    def tick(self, now: float) -> None:
        try:
            self._tick_inner(now)
        finally:
            self._publish_state(now)

    def _tick_inner(self, now: float) -> None:
        files = self._session_files()
        if not self._seeded:
            self.router.seed(files)
            self._seeded = True
            return

        data = self.store.load()
        labels = [a.label for a in self.store.labels(data, PROVIDER)]
        if not labels:
            return
        eng = self._engine(labels)
        active = data.active_by_provider.get(PROVIDER, labels[0])
        mode = data.mode_by_provider.get(PROVIDER, "lock")

        # 활성 라벨 변경 감지(원인 불문: CLI/메뉴/auto) → 관측 초기화 + 구 세션 격리 (설계 §3.3)
        if self._prev_active is not None and active != self._prev_active:
            self._last_observed = None
            self.router.quarantine_seen()
        self._prev_active = active

        switched = False
        for line in self.router.poll(files):
            if switched:
                break  # fallback 후 배치 소비 중단 — 구 계정 라인 오귀속 방지 (설계 §3.3)
            for health_event in parse_account_health(line):
                if health_event.state != "entitlement_unavailable":
                    continue
                self.store.record_account_health(
                    provider=health_event.provider, label=health_event.label,
                    model=health_event.model, state=health_event.state,
                    observed_at=health_event.observed_at, reset_at=health_event.reset_at,
                    error_class=health_event.error_class,
                )
                if mode != "auto" or health_event.provider != PROVIDER or health_event.label != active:
                    continue
                health = {
                    (record["provider"], record["label"], record["model"]): record["state"]
                    for record in self.store.load().account_health
                }
                decision = eng.on_unavailable(
                    provider=PROVIDER, active=active, model=health_event.model,
                    now=now, health=health,
                )
                if decision.kind == "fallback":
                    self.switcher.switch(PROVIDER, decision.target, auto=True)
                    self.router.quarantine_seen()
                    eng.note_switch(now)
                    self._last_event = {"type": "fallback", "from": active,
                                        "to": decision.target, "at": now,
                                        "reason": decision.reason}
                    self._last_observed = None
                    active = decision.target
                    self._prev_active = active
                    switched = True
                    break
            if switched:
                break
            for ev in parse_token_count(line):
                is_short_window = (ev.window_minutes is not None
                                   and ev.window_minutes < SHORT_WINDOW_MAX_MINUTES)
                if is_short_window and ev.limit_name is None:
                    self._last_observed = {
                        "used_percent": ev.used_percent,
                        "resets_at": float(ev.resets_at) if ev.resets_at else None,
                        "at": now,
                    }
                # primary(=labels[0]) 사용 중 리셋시각 추적 (복귀 판단용)
                # short window(5h류)만 기록 — secondary(7d)가 섞이면 복귀 판단이 틀어짐
                if active == labels[0] and ev.resets_at and is_short_window:
                    new_reset = float(ev.resets_at)
                    if new_reset != self._primary_reset_at:
                        self._primary_reset_at = new_reset
                        data2 = self.store.load()
                        data2.primary_reset_at[PROVIDER] = new_reset
                        self.store.save(data2)
                if not is_account_exhausting(ev):
                    continue
                if mode != "auto":
                    continue
                decision = eng.on_exhausted(active=active, now=now)
                if decision.kind == "fallback":
                    self.switcher.switch(PROVIDER, decision.target, auto=True)
                    self.router.quarantine_seen()
                    eng.note_switch(now)
                    self._last_event = {"type": "fallback", "from": active,
                                        "to": decision.target, "at": now,
                                        "reason": decision.reason}
                    self._last_observed = None
                    active = decision.target
                    self._prev_active = active
                    switched = True
                    break

        if mode == "auto":
            decision = eng.on_tick(
                active=active, now=now, primary_label=labels[0],
                primary_reset_at=self._primary_reset_at,
                auto_switched=self.store.load().auto_switched.get(PROVIDER, False),
            )
            if decision.kind == "return":
                self.switcher.switch(PROVIDER, decision.target, auto=False)
                self.router.quarantine_seen()
                eng.note_switch(now)
                self._last_event = {"type": "return", "to": decision.target,
                                    "at": now, "reason": decision.reason}
                self._last_observed = None
                self._prev_active = decision.target

        if now - self._last_reconcile >= self.reconcile_s:
            self.switcher.reconcile(PROVIDER)
            self._last_reconcile = now

    def _publish_state(self, now: float) -> None:
        data = self.store.load()
        payload = {
            "version": 2,
            "updated_at": now,
            "providers": {
                PROVIDER: {
                    "active": data.active_by_provider.get(PROVIDER),
                    "mode": data.mode_by_provider.get(PROVIDER, "lock"),
                    "accounts": [
                        {"label": a.label,
                         "snapshot_ok": self.store.secret_path(a).exists()}
                        for a in self.store.labels(data, PROVIDER)
                    ],
                    "observed": self._last_observed,
                    "last_event": self._last_event,
                    "account_health": [
                        {key: record[key] for key in (
                            "label", "model", "state", "observed_at", "reset_at", "error_class"
                        )}
                        for record in self.store.account_health_for_provider(PROVIDER)
                    ],
                }
            },
        }
        try:
            st = read_claude_status(self.claude_json, self.claude_creds, self.claude_live_json)
        except Exception:
            st = None  # 관측 실패 — claude 키 생략, codex 발행은 계속
        if st is not None and st.ok:
            usage = None
            if st.seven_day_pct is not None:
                usage = {"seven_day_pct": st.seven_day_pct,
                         "resets_at": st.seven_day_resets_at, "at": st.fetched_at}
            payload["providers"]["claude"] = {
                "login_ok": st.login_expires_at is None or st.login_expires_at >= now,
                "login_warning": login_warning(st, now),
                "usage": usage,
            }
        self.store.write_state(payload)

    def run(self) -> None:  # pragma: no cover — 조립 루프, tick이 테스트 단위
        while True:
            self.tick(time.time())
            time.sleep(self.poll_s)
