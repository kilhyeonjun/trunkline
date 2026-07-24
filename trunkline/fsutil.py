"""File primitives: atomic 0600 writes, 0700 dirs, double-read stability.

mtime-based change detection is banned project-wide: credential files are
rewritten by live CLI sessions ("busy files"). Stability = two reads with a
gap returning identical bytes.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


class UnstableFileError(RuntimeError):
    """File kept changing across double-reads; caller should retry later."""


def secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_bytes(data)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def stable_read(path: Path, gap: float = 0.7, retries: int = 3) -> bytes:
    for _ in range(retries):
        first = path.read_bytes()
        time.sleep(gap)
        second = path.read_bytes()
        if first == second:
            return second
    raise UnstableFileError(f"file kept changing: {path}")
