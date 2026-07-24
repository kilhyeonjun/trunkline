"""Session-log attribution. Codex logs carry no account ID (measured), so the
only safe attribution is: on switch, quarantine every file seen so far; only
files first observed after the switch belong to the new account.
All state is memory-only BY DESIGN (review M1): persisting offsets skips
re-seeding after restart (missed signals forever); persisting quarantine
permanently orphans files."""
from __future__ import annotations

from pathlib import Path


class SessionRouter:
    def __init__(self) -> None:
        self._offsets: dict[Path, int] = {}
        self._quarantined: set[Path] = set()

    def seed(self, files: list[Path]) -> None:
        for f in files:
            if f in self._offsets or f in self._quarantined:
                continue
            try:
                self._offsets[f] = f.stat().st_size
            except OSError:
                continue

    def poll(self, files: list[Path]) -> list[str]:
        lines: list[str] = []
        for f in files:
            if f in self._quarantined:
                continue
            # register every observed file explicitly (not just via .get default)
            # so quarantine_seen() (which snapshots self._offsets) catches files
            # seen-but-not-yet-consumed (e.g. no complete line yet).
            self._offsets.setdefault(f, 0)
            offset = self._offsets[f]
            try:
                size = f.stat().st_size
                if size <= offset:
                    continue
                with open(f, "rb") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
            except OSError:
                continue
            # consume only up to the last complete line — a partial tail stays
            # unconsumed until its newline arrives (byte offsets stay consistent,
            # and a cut at b"\n" can never split a UTF-8 sequence)
            boundary = chunk.rfind(b"\n")
            if boundary < 0:
                continue
            consumed = chunk[: boundary + 1]
            self._offsets[f] = offset + len(consumed)
            text = consumed.decode("utf-8", errors="replace")
            lines.extend(l for l in text.splitlines() if l.strip())
        return lines

    def quarantine_seen(self) -> None:
        self._quarantined.update(self._offsets)
        self._offsets.clear()
