from pathlib import Path

from trunkline.router import SessionRouter


def _mk(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_seed_skips_existing_content(tmp_path):
    f = _mk(tmp_path, "a.jsonl", "old1\nold2\n")
    r = SessionRouter()
    r.seed([f])
    assert r.poll([f]) == []          # 과거 내용 무시


def test_poll_returns_only_new_appends(tmp_path):
    f = _mk(tmp_path, "a.jsonl", "old\n")
    r = SessionRouter()
    r.seed([f])
    f.write_text("old\nnew1\nnew2\n")
    assert r.poll([f]) == ["new1", "new2"]
    assert r.poll([f]) == []          # 중복 없음


def test_new_file_after_seed_read_from_start(tmp_path):
    r = SessionRouter()
    r.seed([])
    f = _mk(tmp_path, "b.jsonl", "line1\n")
    assert r.poll([f]) == ["line1"]


def test_quarantine_blocks_old_files(tmp_path):
    """전환 시점까지 관찰된 파일은 격리 — 구 계정 세션의 stale 신호 차단."""
    old = _mk(tmp_path, "old.jsonl", "x\n")
    r = SessionRouter()
    r.seed([old])
    r.quarantine_seen()
    old.write_text("x\nstale-signal\n")
    assert r.poll([old]) == []        # 격리됨
    new = _mk(tmp_path, "new.jsonl", "fresh\n")
    assert r.poll([old, new]) == ["fresh"]   # 새 파일만 새 계정 귀속


def test_observed_but_incomplete_file_still_quarantined(tmp_path):
    """poll()이 완결된 줄 없이 파일을 관찰만 해도(오프셋 미등록 상태로 두면 안 됨)
    quarantine_seen()이 그 파일을 잡아야 한다 — 나중에 줄이 완성돼도 새 계정으로
    새지 않아야 한다."""
    r = SessionRouter()
    r.seed([])
    f = _mk(tmp_path, "old-session.jsonl", "")
    with open(f, "ab") as fh:
        fh.write(b"partial")            # no newline yet — observed, nothing to return
    assert r.poll([f]) == []
    r.quarantine_seen()                 # switch happens here
    with open(f, "ab") as fh:
        fh.write(b"-stale-from-old-account\n")
    assert r.poll([f]) == []            # must NOT leak past quarantine


def test_vanished_file_ignored(tmp_path):
    f = _mk(tmp_path, "a.jsonl", "x\n")
    r = SessionRouter()
    r.seed([f])
    f.unlink()
    assert r.poll([f]) == []


def test_multibyte_content_survives_offset_math(tmp_path):
    f = _mk(tmp_path, "a.jsonl", "")
    r = SessionRouter()
    r.seed([f])
    with open(f, "ab") as fh:
        fh.write("한글줄1\n".encode())
    assert r.poll([f]) == ["한글줄1"]
    with open(f, "ab") as fh:
        fh.write("한글줄2\n".encode())
    assert r.poll([f]) == ["한글줄2"]


def test_partial_line_waits_for_newline(tmp_path):
    f = _mk(tmp_path, "a.jsonl", "")
    r = SessionRouter()
    r.seed([f])
    with open(f, "ab") as fh:
        fh.write(b"partial")            # no newline yet
    assert r.poll([f]) == []            # not consumed
    with open(f, "ab") as fh:
        fh.write(b"-done\n")
    assert r.poll([f]) == ["partial-done"]   # one complete line
