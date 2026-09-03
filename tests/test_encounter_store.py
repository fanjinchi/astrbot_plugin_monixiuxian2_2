"""Tests for core/encounter_store.py - the shared pending-encounter table.

Covers pend/get_active/consume, lazy expiry, same-kind overwrite refresh and
per-kind/per-player independence (add-rift-encounters design D1/D8).
"""

import pytest

from tests.helpers import load_module

_mod = load_module("encounter_store", "core/encounter_store.py")
EncounterStore = _mod.EncounterStore
KIND_PUZZLE = _mod.KIND_PUZZLE
KIND_BEAST = _mod.KIND_BEAST
KIND_LEGACY = _mod.KIND_LEGACY


def _store(ttl: int = 600, start: float = 1000.0):
    """Build a store with a controllable fake clock; returns (store, clock)."""
    clock = [start]
    return EncounterStore(ttl_seconds=ttl, time_fn=lambda: clock[0]), clock


def test_pend_then_get_active_returns_entry():
    store, clock = _store()
    entry = store.pend("u1", KIND_PUZZLE, {"x": 1})
    got = store.get_active("u1", KIND_PUZZLE)
    assert got is entry
    assert got.payload == {"x": 1}
    assert got.created_at == clock[0]
    assert got.expires_at == clock[0] + 600


def test_get_active_missing_returns_none():
    store, _ = _store()
    assert store.get_active("u1", KIND_PUZZLE) is None
    assert store.consume("u1", KIND_PUZZLE) is None


def test_lazy_expiry_drops_entry_on_read():
    store, clock = _store(ttl=10)
    store.pend("u1", KIND_BEAST)
    clock[0] += 9
    assert store.get_active("u1", KIND_BEAST) is not None
    clock[0] += 2  # 越过 expires_at
    assert store.get_active("u1", KIND_BEAST) is None
    # 过期判定后条目已清除（二次读取仍 None）
    assert store.get_active("u1", KIND_BEAST) is None


def test_same_kind_pend_overwrites_and_refreshes():
    store, clock = _store(ttl=10)
    store.pend("u1", KIND_PUZZLE, {"v": 1})
    clock[0] += 8
    entry2 = store.pend("u1", KIND_PUZZLE, {"v": 2})
    got = store.get_active("u1", KIND_PUZZLE)
    assert got is entry2
    assert got.payload == {"v": 2}
    assert got.expires_at == clock[0] + 10  # 过期时间被重置


def test_kinds_and_players_are_independent():
    store, _ = _store()
    store.pend("u1", KIND_PUZZLE)
    store.pend("u1", KIND_BEAST)
    store.pend("u1", KIND_LEGACY)
    assert store.get_active("u1", KIND_PUZZLE) is not None
    assert store.get_active("u1", KIND_BEAST) is not None
    assert store.get_active("u1", KIND_LEGACY) is not None
    # 不同玩家互不影响
    assert store.get_active("u2", KIND_PUZZLE) is None


def test_consume_removes_entry():
    store, _ = _store()
    store.pend("u1", KIND_PUZZLE)
    entry = store.consume("u1", KIND_PUZZLE)
    assert entry is not None
    assert store.get_active("u1", KIND_PUZZLE) is None


def test_consume_expired_returns_none():
    store, clock = _store(ttl=5)
    store.pend("u1", KIND_PUZZLE)
    clock[0] += 10
    assert store.consume("u1", KIND_PUZZLE) is None


def test_pend_ttl_override():
    store, clock = _store(ttl=600)
    entry = store.pend("u1", KIND_PUZZLE, ttl=30)
    assert entry.expires_at == clock[0] + 30


def test_unknown_kind_rejected():
    store, _ = _store()
    with pytest.raises(ValueError):
        store.pend("u1", "unknown")
