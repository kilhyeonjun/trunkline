from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .claude_status import LIVE_JSON_DEFAULT, age_text, login_warning, read_claude_status
from .daemon import Daemon
from .engine import AccountHealthEvent
from .identity import decode_identity
from .providerio import CodexConfigIO, probe_codex_health
from .store import Account, AccountStore, StoreData
from .switcher import Switcher, SwitchError
from .usage import read_usage

SB_ROOT = Path.home() / ".trunkline"
CODEX_HOME = Path.home() / ".codex"
CLAUDE_JSON = Path.home() / ".claude.json"
CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"
PROVIDER = "codex"


def _wiring():
    store = AccountStore(root=SB_ROOT, codex_home=CODEX_HOME)
    io = CodexConfigIO(CODEX_HOME)
    return store, io, Switcher(store, {PROVIDER: io})


def _cmd_init(args) -> int:
    store, io, _ = _wiring()
    found = sorted(p.parent.name for p in (CODEX_HOME / "accounts").glob("*/auth.json"))
    if not found:
        print("no accounts under ~/.codex/accounts/ — run: codex login (then adopt)", file=sys.stderr)
        return 1
    if args.priority:
        order = [x.strip() for x in args.priority.split(",") if x.strip()]
        unknown = set(order) - set(found)
        if unknown:
            print(f"unknown labels: {sorted(unknown)}", file=sys.stderr)
            return 1
        order = list(dict.fromkeys(order))   # 중복 label 제거(예: --priority a,a) — usage 행 크래시 방어
        found = order + [x for x in found if x not in order]
    data = StoreData(
        accounts=[Account(label, PROVIDER) for label in found],
        active_by_provider={}, mode_by_provider={PROVIDER: "lock"},
        auto_switched={PROVIDER: False}, preferred={},
    )
    store.save(data)
    Switcher(store, {PROVIDER: CodexConfigIO(CODEX_HOME)}).reconcile(PROVIDER)
    print(f"initialized: {', '.join(found)} (mode: lock)")
    return 0


def _cmd_status(args) -> int:
    store, io, sw = _wiring()
    data = store.load()
    live = sw.current_label(PROVIDER)
    print(f"mode: {data.mode_by_provider.get(PROVIDER, 'lock')}")
    print(f"live: {live or 'unknown'}")
    for a in store.labels(data, PROVIDER):
        mark = "*" if a.label == live else " "
        exists = store.secret_path(a).exists()
        print(f" {mark} {a.label}: {'ok' if exists else '스냅샷 없음'}")
    st = read_claude_status(CLAUDE_JSON, CLAUDE_CREDS, LIVE_JSON_DEFAULT)
    if st.ok:
        warn = login_warning(st, time.time())
        tail = f" · ⚠️ {warn}" if warn else " · 로그인 OK"
        print(f"claude: {st.email or '-'} ({st.tier or '-'}){tail}")
    else:
        print(f"claude: 상태 불명 ({st.error})")
    return 0


def _cmd_switch(args) -> int:
    _, _, sw = _wiring()
    try:
        sw.switch(PROVIDER, args.label)
    except SwitchError as exc:
        print(f"switch failed: {exc}", file=sys.stderr)
        return 1
    print(f"{args.label}로 전환됨 (새 codex 세션부터 적용)")
    return 0


def _set_mode(mode: str, label: str | None = None) -> int:
    store, _, sw = _wiring()
    data = store.load()
    data.mode_by_provider[PROVIDER] = mode
    if label:
        data.preferred[PROVIDER] = label
    store.save(data)
    if label:
        try:
            sw.switch(PROVIDER, label)
        except SwitchError as exc:
            print(f"mode set but switch failed: {exc}", file=sys.stderr)
            return 1
    print(f"mode: {mode}" + (f" ({label})" if label else ""))
    return 0


def _cmd_adopt(args) -> int:
    _, _, sw = _wiring()
    try:
        sw.adopt(PROVIDER, args.label)
    except SwitchError as exc:
        print(f"adopt failed: {exc}", file=sys.stderr)
        return 1
    print(f"adopted live auth as {args.label}")
    return 0


def _cmd_login(args) -> int:
    """라이브 무접촉 재로그인: CODEX_HOME 격리 (리뷰 M-2)."""
    store, _, _ = _wiring()
    home = store.secret_path(Account(args.label, PROVIDER)).parent
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    codex = shutil.which("codex")
    if not codex:
        print("codex executable not found", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    return subprocess.call([codex, "login", "--device-auth"], env=env)


def _window_label(minutes: int | None) -> str | None:
    """wham limit_window_seconds 유래 분 단위 → 사람용 라벨. None(창 미상)은 생략.
    GaugeSpec.windowTitle과 동기 — 구간 매핑(300/10080/<60/<2880/else) 변경 시 양쪽 테스트
    (tests/test_cli.py ↔ GaugeSpecTests.swift) 동시 갱신 필요."""
    if minutes is None:
        return None
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "7d"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 2880:
        return f"{minutes // 60}h"
    return f"{minutes // 1440}d"


def _usage_part(label: str | None, pct: float | None) -> str | None:
    if pct is None and label is None:
        return None
    val = f"{pct:g}%" if pct is not None else "-"
    return f"{label} {val}" if label else val


def _account_plan(secret_path: Path) -> str | None:
    """계정 auth.json → 구독 플랜(chatgpt_plan_type). 읽기/파싱 실패는 None (크래시 금지)."""
    try:
        ident = decode_identity(secret_path.read_bytes())
    except OSError:
        return None
    return ident.plan if ident else None


def _auth_path(store, io, sw, account: Account) -> Path:
    """활성 계정은 스냅샷이 아니라 live auth를 읽는다. codex CLI는 live만 in-place
    회전시키고 스냅샷 흡수는 switch 시점에만 일어나므로, lock 모드에서는 스냅샷
    토큰이 무한히 낡아 usage가 HTTP 401을 받는다. 활성 판정은 store 기록이 아니라
    live 신원 매칭(current_label) — 신원 불일치 시 추측 금지하고 스냅샷으로 폴백."""
    if sw.current_label(account.provider) == account.label:
        return io.live_path
    return store.secret_path(account)


def _cmd_usage(args) -> int:
    import json as _json
    from dataclasses import asdict, replace
    store, io, sw = _wiring()
    data = store.load()
    paths = {a.label: _auth_path(store, io, sw, a) for a in store.labels(data, PROVIDER)}
    rows = [replace(read_usage(a.label, paths[a.label]),
                     plan=_account_plan(paths[a.label]))
            for a in store.labels(data, PROVIDER)]
    st = read_claude_status(CLAUDE_JSON, CLAUDE_CREDS, LIVE_JSON_DEFAULT)
    if getattr(args, "json", False):
        print(_json.dumps({"codex": [asdict(r) for r in rows], "claude": asdict(st)}))
        return 0
    for row in rows:
        label = f"{row.label} ({row.plan})" if row.plan else row.label
        if row.ok:
            parts = [
                _usage_part(_window_label(row.primary_window_minutes), row.primary_used),
                _usage_part(_window_label(row.secondary_window_minutes), row.secondary_used),
            ]
            print(f"{label}: " + " · ".join(p for p in parts if p is not None))
        else:
            print(f"{label}: {'stale — ' if row.stale else ''}{row.error}")
    if st.ok:
        fh = f"{st.five_hour_pct:g}%" if st.five_hour_pct is not None else "-"
        sd = f"{st.seven_day_pct:g}%" if st.seven_day_pct is not None else "-"
        age = age_text(time.time(), st.fetched_at)
        print(f"claude: 5h {fh} · 7d {sd}" + (f" ({age} 기준)" if age else ""))
    else:
        print(f"claude: 상태 불명 ({st.error})")
    return 0


def _cmd_daemon(args) -> int:  # pragma: no cover
    store, io, sw = _wiring()
    Daemon(store, sw, io, sessions_dir=CODEX_HOME / "sessions").run()
    return 0


def _bounded_probe_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be numeric") from exc
    if not math.isfinite(timeout) or not 1 <= timeout <= 30:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 30 seconds")
    return timeout


def _print_health(records: list[dict[str, object]]) -> None:
    if not records:
        print("codex: unknown (no persisted health)")
        return
    for record in records:
        print(
            f"{record['label']} {record['model']} {record['state']} "
            f"({record['error_class'] or '-'})"
        )


def _cmd_health(args) -> int:
    store, _, _ = _wiring()
    data = store.load()
    if not args.probe:
        _print_health(store.account_health_for_provider(PROVIDER))
        return 0
    if not args.model.strip():
        print("health --probe requires a nonempty --model", file=sys.stderr)
        return 2
    active = data.active_by_provider.get(PROVIDER)
    if not active:
        print("codex: unknown (no active account)", file=sys.stderr)
        return 1
    outcome = probe_codex_health(codex_path="codex", model=args.model, timeout=args.timeout)
    event = AccountHealthEvent(
        provider=PROVIDER, label=active, model=args.model, state=outcome.state,
        observed_at=int(time.time()), error_class=outcome.error_class,
    )
    store.record_account_health(
        provider=event.provider, label=event.label, model=event.model,
        state=event.state, observed_at=event.observed_at, reset_at=event.reset_at,
        error_class=event.error_class,
    )
    _print_health([{
        "label": event.label, "model": event.model, "state": event.state,
        "error_class": event.error_class,
    }])
    return 0 if event.state == "healthy" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trunkline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--priority", default=""); p.set_defaults(fn=_cmd_init)
    sub.add_parser("status").set_defaults(fn=_cmd_status)
    p = sub.add_parser("switch"); p.add_argument("label"); p.set_defaults(fn=_cmd_switch)
    p = sub.add_parser("pin"); p.add_argument("label")
    p.set_defaults(fn=lambda a: _set_mode("pin", a.label))
    sub.add_parser("auto").set_defaults(fn=lambda a: _set_mode("auto"))
    p = sub.add_parser("lock"); p.add_argument("label")
    p.set_defaults(fn=lambda a: _set_mode("lock", a.label))
    p = sub.add_parser("adopt"); p.add_argument("label"); p.set_defaults(fn=_cmd_adopt)
    p = sub.add_parser("login"); p.add_argument("label"); p.set_defaults(fn=_cmd_login)
    p = sub.add_parser("usage")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_cmd_usage)
    p = sub.add_parser("health")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--model", default="")
    p.add_argument("--timeout", type=_bounded_probe_timeout, default=10.0)
    p.set_defaults(fn=_cmd_health)
    sub.add_parser("daemon").set_defaults(fn=_cmd_daemon)
    from .cutover import add_cutover_parser
    add_cutover_parser(sub)
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
