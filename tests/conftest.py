import json
from pathlib import Path

import pytest

from trunkline import claude_status, daemon


@pytest.fixture(autouse=True)
def _isolate_claude_live_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """실홈 ~/.trunkline/claude_usage_live.json 격리 — 실기기 라이브 파일이 있어도
    live_json 인자를 명시하지 않는 테스트는 항상 부재 경로를 봐야 함."""
    fake = tmp_path / "no_live.json"
    # 시그니처에 default 파라미터가 추가되면 아래 (fake,) 슬롯이 조용히 어긋남 — 즉시 실패로 게이트.
    assert claude_status.read_claude_status.__defaults__ == (claude_status.LIVE_JSON_DEFAULT,)
    monkeypatch.setattr(claude_status, "LIVE_JSON_DEFAULT", fake)
    # read_claude_status(live_json=LIVE_JSON_DEFAULT)는 def 시점에 바인딩된 기본값이라
    # 위 setattr만으로는 안 바뀜 — 함수 기본값 자체도 같이 패치.
    monkeypatch.setattr(claude_status.read_claude_status, "__defaults__", (fake,))
    # daemon.py가 `from .claude_status import LIVE_JSON_DEFAULT`로 별도 바인딩 —
    # 그쪽 이름도 같이 패치해야 Daemon(claude_live_json=None) 경로가 격리됨.
    monkeypatch.setattr(daemon, "LIVE_JSON_DEFAULT", fake)


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    home = tmp_path / ".codex"
    (home / "accounts").mkdir(parents=True)
    return home


@pytest.fixture
def sb_root(tmp_path: Path) -> Path:
    root = tmp_path / ".trunkline"
    root.mkdir()
    return root


def _cfg(tmp_path, five=0, seven=12, resets="2026-07-20T22:00:00.304197+00:00",
         fetched_ms=1_784_511_168_429):
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({
        "oauthAccount": {"emailAddress": "h@x.net", "organizationRateLimitTier": "max_20x"},
        "cachedUsageUtilization": {
            "fetchedAtMs": fetched_ms,
            "utilization": {
                "five_hour": {"utilization": five, "resets_at": resets},
                "seven_day": {"utilization": seven, "resets_at": resets},
            },
        },
    }))
    return p


def _creds(tmp_path, refresh_exp_ms=1_785_300_106_975):
    p = tmp_path / "creds.json"
    p.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "SECRET-A", "refreshToken": "SECRET-R",
        "refreshTokenExpiresAt": refresh_exp_ms}}))
    return p
