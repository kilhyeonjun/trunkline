"""One-time cutover from legacy codex-account (review C-4).

Order is load-bearing: the legacy LaunchAgent rotates tokens every 900s and
re-links auth.json; it must be booted out BEFORE we first touch auth.json,
or we get a clobber loop + dual rotation actors."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .fsutil import atomic_write

LEGACY_LABEL = "com.kilhyeonjun.codex-account-auto"


def run_cutover(codex_home: Path, launchctl=subprocess.call,
                uid: int | None = None, home: Path | None = None) -> list[str]:
    log: list[str] = []
    uid = os.getuid() if uid is None else uid
    home = Path.home() if home is None else home

    # 1) 구 에이전트 해제 — auth.json 조작 전 필수
    rc = launchctl(["launchctl", "bootout", f"gui/{uid}/{LEGACY_LABEL}"])
    log.append(f"bootout {LEGACY_LABEL}: rc={rc} (rc!=0 = 이미 미로드, 정상)")

    # 2) 심링크 해소
    live = codex_home / "auth.json"
    if not live.exists() and not live.is_symlink():
        log.append("no live auth.json — nothing to convert")
    elif live.is_symlink():
        data = live.resolve().read_bytes()
        live.unlink()
        atomic_write(live, data)
        log.append("symlink resolved to regular file (store original untouched)")
    else:
        log.append("auth.json already a regular file")

    # 3) 구 plist 비활성 rename
    plist = home / "Library" / "LaunchAgents" / f"{LEGACY_LABEL}.plist"
    if plist.exists():
        plist.rename(plist.with_suffix(".plist.disabled"))
        log.append("legacy plist renamed to .disabled")
    return log


def add_cutover_parser(sub) -> None:
    p = sub.add_parser("cutover", help="one-time migration from legacy codex-account")
    p.set_defaults(fn=_cmd_cutover)


def _cmd_cutover(args) -> int:
    from .cli import CODEX_HOME
    for line in run_cutover(CODEX_HOME):
        print(line)
    print("cutover complete. next: trunkline init --priority personal,company")
    return 0
