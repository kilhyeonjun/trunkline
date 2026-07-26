"""Claude Code 상태 pure reader. 값 접근·출력·전송 없음 계약 (P6 설계 §1.1):
json.load 특성상 토큰이 일시적으로 메모리에 올라오지만, 만료 int 1개만 추출하고
dict 참조를 즉시 폐기한다. error는 고정 enum만 — 파싱 내용 포맷 금지 (0644
state.json 유출 경로 차단). 네트워크·Keychain·회전 코드 금지 (grep 게이트)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WARN_WINDOW_S = 5 * 86400.0


@dataclass(frozen=True)
class ClaudeStatus:
    ok: bool
    email: str | None
    tier: str | None
    five_hour_pct: float | None
    five_hour_resets_at: float | None
    seven_day_pct: float | None
    seven_day_resets_at: float | None
    fetched_at: float | None
    login_expires_at: float | None
    error: str | None


def _err(code: str) -> ClaudeStatus:
    return ClaudeStatus(ok=False, email=None, tier=None, five_hour_pct=None,
                        five_hour_resets_at=None, seven_day_pct=None,
                        seven_day_resets_at=None, fetched_at=None,
                        login_expires_at=None, error=code)


def _iso_to_epoch(s) -> float | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


LIVE_JSON_DEFAULT = Path.home() / ".trunkline" / "claude_usage_live.json"


def _read_live(live_json: Path | None) -> dict | None:
    """statusline이 tee한 신선 usage. 파싱 실패·부재는 조용히 None (폴백)."""
    if live_json is None:
        return None
    try:
        data = json.loads(live_json.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_claude_status(claude_json: Path, credentials_json: Path,
                        live_json: Path | None = LIVE_JSON_DEFAULT) -> ClaudeStatus:
    # 자격 파일은 만료 경고 하나만 제공하는 부가 입력이다. macOS Claude Code는 OAuth를
    # Keychain에 보관해 파일이 아예 없고, Keychain 읽기는 §1.1 grep 게이트로 금지돼 있다.
    # 따라서 부재·손상·형식 불일치는 만료 미상으로 격하하고 usage 보고는 계속한다.
    exp_ms = None
    try:
        creds = json.loads(credentials_json.read_text())
    except (OSError, ValueError):
        creds = None
    if isinstance(creds, dict):
        exp_ms = _num((creds.get("claudeAiOauth") or {}).get("refreshTokenExpiresAt"))
    del creds  # 토큰 dict 즉시 폐기 (설계 §1.1)

    try:
        cfg = json.loads(claude_json.read_text())
    except OSError:
        return _err("config_missing")
    except ValueError:
        return _err("parse_error")
    cache = cfg.get("cachedUsageUtilization") or {}
    util = cache.get("utilization") or {}
    if not util:
        return _err("cache_missing")
    acct = cfg.get("oauthAccount") or {}
    fh = util.get("five_hour") or {}
    sd = util.get("seven_day") or {}
    fetched_ms = _num(cache.get("fetchedAtMs"))
    fetched_at = fetched_ms / 1000.0 if fetched_ms is not None else None
    five_hour_pct = _num(fh.get("utilization"))
    five_hour_resets_at = _iso_to_epoch(fh.get("resets_at"))
    seven_day_pct = _num(sd.get("utilization"))
    seven_day_resets_at = _iso_to_epoch(sd.get("resets_at"))

    live = _read_live(live_json)
    live_at = _num(live.get("at")) if live else None
    if live_at is not None and (fetched_at is None or live_at > fetched_at):
        five_hour_pct = _num(live.get("five_hour_pct"))
        five_hour_resets_at = _num(live.get("five_hour_resets_at"))
        seven_day_pct = _num(live.get("seven_day_pct"))
        seven_day_resets_at = _num(live.get("seven_day_resets_at"))
        fetched_at = live_at

    return ClaudeStatus(
        ok=True,
        email=acct.get("emailAddress"),
        tier=acct.get("organizationRateLimitTier"),
        five_hour_pct=five_hour_pct,
        five_hour_resets_at=five_hour_resets_at,
        seven_day_pct=seven_day_pct,
        seven_day_resets_at=seven_day_resets_at,
        fetched_at=fetched_at,
        login_expires_at=exp_ms / 1000.0 if exp_ms is not None else None,
        error=None,
    )


def login_warning(st: ClaudeStatus, now: float) -> str | None:
    exp = st.login_expires_at
    if exp is None:
        return None
    if exp < now:
        return "재로그인 필요: claude auth login"
    remain = exp - now
    if remain < WARN_WINDOW_S:
        return f"만료 임박 D-{int(remain // 86400)}"
    return None


def age_text(now: float, at: float | None) -> str | None:
    if at is None:
        return None
    s = max(0.0, now - at)
    if s < 3600:
        return f"{int(s // 60)}분 전"
    if s < 86400:
        return f"{int(s // 3600)}시간 전"
    return f"{int(s // 86400)}일 전"
