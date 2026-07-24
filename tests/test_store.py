import json
from pathlib import Path

from trunkline.store import Account, AccountStore, StoreData


def _store(sb_root: Path, codex_home: Path) -> AccountStore:
    return AccountStore(root=sb_root, codex_home=codex_home)


def test_load_empty_when_missing(sb_root, codex_home):
    data = _store(sb_root, codex_home).load()
    assert data.accounts == []
    assert data.mode_by_provider == {}


def test_save_load_roundtrip(sb_root, codex_home):
    s = _store(sb_root, codex_home)
    data = StoreData(
        accounts=[Account("personal", "codex"), Account("company", "codex")],
        active_by_provider={"codex": "personal"},
        mode_by_provider={"codex": "auto"},
        auto_switched={"codex": False},
        preferred={},
    )
    s.save(data)
    loaded = s.load()
    assert loaded == data
    assert oct((sb_root / "accounts.json").stat().st_mode & 0o777) == "0o600"


def test_corrupt_backed_up_not_lost(sb_root, codex_home):
    """Mobius 실패 기록 13: corrupt 시 백업 후 빈 스토어 — 계정 영구 유실 방지."""
    (sb_root / "accounts.json").write_text("{broken json")
    s = _store(sb_root, codex_home)
    data = s.load()
    assert data.accounts == []
    backups = list(sb_root.glob("accounts.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{broken json"


def test_secret_path_is_adapter_owned(sb_root, codex_home):
    """리뷰 M-1: secret은 ~/.codex/accounts/<label>/auth.json 재사용."""
    s = _store(sb_root, codex_home)
    p = s.secret_path(Account("personal", "codex"))
    assert p == codex_home / "accounts" / "personal" / "auth.json"


def test_labels_filters_by_provider(sb_root, codex_home):
    s = _store(sb_root, codex_home)
    data = StoreData(
        accounts=[Account("a", "codex"), Account("b", "claude"), Account("c", "codex")],
        active_by_provider={}, mode_by_provider={}, auto_switched={}, preferred={},
    )
    assert [a.label for a in s.labels(data, "codex")] == ["a", "c"]


def test_write_state(sb_root, codex_home):
    s = _store(sb_root, codex_home)
    s.write_state({"version": 1, "providers": {}})
    loaded = json.loads((sb_root / "state.json").read_text())
    assert loaded["version"] == 1


def test_two_corruptions_both_backed_up(sb_root, codex_home):
    """같은 초 내 이중 corrupt도 각각 백업 — never silently destroy."""
    s = _store(sb_root, codex_home)
    (sb_root / "accounts.json").write_text("{bad1")
    s.load()
    (sb_root / "accounts.json").write_text("{bad2")
    s.load()
    backups = sorted(sb_root.glob("accounts.json.corrupt-*"))
    assert len(backups) == 2
    assert {b.read_text() for b in backups} == {"{bad1", "{bad2"}
