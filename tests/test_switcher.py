import base64
import json
from pathlib import Path

import pytest

from trunkline.providerio import CodexConfigIO
from trunkline.store import Account, AccountStore, StoreData
from trunkline.switcher import Switcher, SwitchError


def _auth(account_id: str) -> bytes:
    return json.dumps({"tokens": {"account_id": account_id}}).encode()


def test_switcher_accepts_injected_stability_gap(sb_root, codex_home):
    """Tests may remove the wait without changing the production default."""
    store = AccountStore(root=sb_root, codex_home=codex_home)
    io = CodexConfigIO(codex_home)

    switcher = Switcher(store, {"codex": io}, stability_gap=0)

    assert switcher.stability_gap == 0


@pytest.fixture
def env(sb_root, codex_home):
    store = AccountStore(root=sb_root, codex_home=codex_home)
    io = CodexConfigIO(codex_home)
    sw = Switcher(store, {"codex": io}, stability_gap=0)
    data = StoreData(
        accounts=[Account("personal", "codex"), Account("company", "codex")],
        active_by_provider={"codex": "personal"},
        mode_by_provider={"codex": "auto"},
        auto_switched={"codex": False},
        preferred={},
    )
    store.save(data)
    for label, acct in [("personal", "acct-p"), ("company", "acct-c")]:
        p = store.secret_path(Account(label, "codex"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_auth(acct))
    (codex_home / "auth.json").write_bytes(_auth("acct-p"))
    return store, io, sw


def test_switcher_default_passes_production_stability_gap(env, monkeypatch):
    store, io, _ = env
    gaps = []

    def read_stable_live_secret(*, gap: float = 0.7) -> bytes:
        gaps.append(gap)
        return io.read_live_secret()

    monkeypatch.setattr(io, "read_stable_live_secret", read_stable_live_secret)

    Switcher(store, {"codex": io}).switch("codex", "company")

    assert gaps == [0.7]


def test_current_label_matches_by_account_id(env):
    store, io, sw = env
    assert sw.current_label("codex") == "personal"


def test_switch_swaps_bytes_and_saves_back(env):
    store, io, sw = env
    # 라이브가 CLI 회전으로 이미 새 바이트일 때: 떠나기 전 흡수
    rotated = json.dumps({"tokens": {"account_id": "acct-p", "note": "rotated"}}).encode()
    (io.codex_home / "auth.json").write_bytes(rotated)

    sw.switch("codex", "company")

    assert (io.codex_home / "auth.json").read_bytes() == _auth("acct-c")   # 스왑됨
    personal_path = store.secret_path(Account("personal", "codex"))
    assert personal_path.read_bytes() == rotated                            # 회전본 흡수됨
    assert store.load().active_by_provider["codex"] == "company"
    assert store.load().auto_switched["codex"] is False


def test_switch_auto_flag_persisted(env):
    store, io, sw = env
    sw.switch("codex", "company", auto=True)
    assert store.load().auto_switched["codex"] is True


def test_switch_unknown_label_raises(env):
    _, _, sw = env
    with pytest.raises(SwitchError):
        sw.switch("codex", "nope")


def test_adopt_absorbs_live(env):
    store, io, sw = env
    (io.codex_home / "auth.json").write_bytes(_auth("acct-new"))
    sw.adopt("codex", "third")
    assert store.secret_path(Account("third", "codex")).read_bytes() == _auth("acct-new")
    assert any(a.label == "third" for a in store.load().accounts)


def test_adopt_existing_label_raises(env):
    _, _, sw = env
    with pytest.raises(SwitchError):
        sw.adopt("codex", "personal")


def test_switch_to_self_keeps_rotated_live(env):
    """스위치-투-셀프: 라이브가 CLI 회전으로 이미 새 바이트일 때 같은 라벨로
    전환해도 회전본이 흡수되어야 하고, 라이브는 회전본을 유지해야 한다
    (target_bytes를 save-back '이전'에 읽으면 라이브가 stale 스냅샷으로 되돌아감)."""
    store, io, sw = env
    rotated = json.dumps({"tokens": {"account_id": "acct-p", "note": "rotated"}}).encode()
    (io.codex_home / "auth.json").write_bytes(rotated)

    sw.switch("codex", "personal")   # active label == target label

    assert (io.codex_home / "auth.json").read_bytes() == rotated   # 라이브 유지
    personal_path = store.secret_path(Account("personal", "codex"))
    assert personal_path.read_bytes() == rotated                    # 스냅샷도 흡수됨


def test_reconcile_follows_live(env):
    """라이브가 진실 — 외부에서 라이브가 company로 바뀌면 스토어가 추종."""
    store, io, sw = env
    (io.codex_home / "auth.json").write_bytes(_auth("acct-c"))
    sw.reconcile("codex")
    assert store.load().active_by_provider["codex"] == "company"
    # 라이브는 건드리지 않는다
    assert (io.codex_home / "auth.json").read_bytes() == _auth("acct-c")
