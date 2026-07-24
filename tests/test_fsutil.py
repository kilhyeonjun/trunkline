import os
import threading
import time
from pathlib import Path

import pytest

from trunkline.fsutil import UnstableFileError, atomic_write, secure_dir, stable_read


def test_atomic_write_creates_0600(tmp_path: Path):
    p = tmp_path / "a.json"
    atomic_write(p, b'{"x":1}')
    assert p.read_bytes() == b'{"x":1}'
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_atomic_write_no_partial_on_existing(tmp_path: Path):
    p = tmp_path / "a.json"
    atomic_write(p, b"old")
    atomic_write(p, b"new")
    assert p.read_bytes() == b"new"
    # temp 잔여물 없음
    assert list(tmp_path.iterdir()) == [p]


def test_secure_dir(tmp_path: Path):
    d = tmp_path / "sec"
    secure_dir(d)
    assert oct(d.stat().st_mode & 0o777) == "0o700"


def test_stable_read_returns_when_unchanged(tmp_path: Path):
    p = tmp_path / "f"
    p.write_bytes(b"stable")
    assert stable_read(p, gap=0.01) == b"stable"


def test_stable_read_raises_on_churn(tmp_path: Path):
    p = tmp_path / "f"
    p.write_bytes(b"v0")
    stop = threading.Event()

    def churn():
        i = 0
        while not stop.is_set():
            p.write_bytes(f"v{i}".encode())
            i += 1
            time.sleep(0.005)

    t = threading.Thread(target=churn, daemon=True)
    t.start()
    try:
        with pytest.raises(UnstableFileError):
            stable_read(p, gap=0.02, retries=2)
    finally:
        stop.set()
        t.join()
