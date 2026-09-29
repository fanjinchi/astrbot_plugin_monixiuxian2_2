"""Tests for managers/impart_pk_manager.py (PK snatch battle outcomes).

Covers the three battle outcomes of ``ImpartPkManager.challenge_impart``
(draw / attacker win / defender win), the concurrent-transfer conflict
branch, and the pre-check rejection branches. The combat engine is stubbed
so ``winner_side`` / ``winner_id`` are controlled directly — these are the
two consumption sites rewritten by the combat-result-winner-identity change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

# ---------------------------------------------------------------------------
# Module loading: mirror the proven sequence from test_impart_manager.py.
# ---------------------------------------------------------------------------
load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models")
load_package_module(
    "models_extended.py", "astrbot_plugin_monixiuxian2_2.models_extended"
)
load_package_module(
    "data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager"
)
load_package_module(
    "data/database_extended.py",
    "astrbot_plugin_monixiuxian2_2.data.database_extended",
)
load_package_module("config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager")

# Load the real combat_manager under the package-qualified name: the time-skip
# registry imports providers by that dotted name (TIME_SKIP_ENTRIES), so a
# synthetic stub here would break every other test module that relies on it.
load_package_module(
    "managers/combat_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.combat_manager",
)

load_package_module(
    "managers/impart_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.impart_manager",
)
_pk_mod = load_package_module(
    "managers/impart_pk_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.impart_pk_manager",
)
ImpartPkManager = _pk_mod.ImpartPkManager
Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player


def _make_player(user_id: str, experience: int = 0) -> Player:
    """Build a minimal Player for PK battle tests."""
    return Player(user_id=user_id, user_name=f"道友{user_id}", experience=experience)


def _make_deps(
    winner_side: str = "fighter1",
    winner_id: str | None = "attacker_1",
    transferred: bool = True,
):
    """Build stubbed engine/impart/db and the manager under test.

    Args:
        winner_side: Value returned by the stubbed ``resolve_combat``.
        winner_id: Winning fighter's user_id (None for a draw).
        transferred: Whether the stubbed ``transfer_legacy`` succeeds.

    Returns:
        A tuple of (manager, engine, impart_mgr, db) for assertions.
    """
    engine = MagicMock()
    engine.build_fighter_from_player = AsyncMock(
        side_effect=lambda player, is_attacker=False: SimpleNamespace(
            user_id=player.user_id, name=player.user_name
        )
    )
    # resolve_combat is a SYNC engine method (combat_manager.py:277); only
    # build_fighter_from_player is async, so plain MagicMock is correct here.
    engine.resolve_combat = MagicMock(
        return_value=SimpleNamespace(
            winner_side=winner_side,
            winner_id=winner_id,
            combat_log=["第 1 回合", "战斗结束"],
        )
    )
    combat_mgr = MagicMock(engine=engine)

    impart_mgr = MagicMock()
    impart_mgr.get_snatch_protection_remaining = AsyncMock(return_value=0)
    impart_mgr.can_challenge = AsyncMock(return_value=(True, 0))
    impart_mgr.select_snatch_target = AsyncMock(
        return_value=SimpleNamespace(id="impart_1", legacy_type="common")
    )
    impart_mgr.transfer_legacy = AsyncMock(
        return_value=SimpleNamespace(ok=True) if transferred else None
    )
    impart_mgr.record_snatch_protection = AsyncMock()
    impart_mgr.record_challenge_failure = AsyncMock()
    impart_mgr.get_type_name = MagicMock(return_value="common")

    db = MagicMock()
    db.update_player = AsyncMock()

    manager = ImpartPkManager(db, combat_mgr, impart_mgr)
    return manager, engine, impart_mgr, db


@pytest.mark.asyncio
async def test_draw_no_transfer():
    """A draw returns (False, ...) with rewards['draw'] and touches nothing."""
    manager, engine, impart_mgr, db = _make_deps(winner_side="draw", winner_id=None)
    attacker, defender = _make_player("attacker_1", 1000), _make_player("defender_1")

    ok, battle_text, rewards = await manager.challenge_impart(attacker, defender)

    assert ok is False
    assert battle_text == "战斗结束"
    assert rewards["draw"] is True
    assert rewards["target_instance_id"] == "impart_1"
    assert rewards["target_type"] == "common"
    # Fighter ordering contract: attacker is fighter1 (winner_side is relative
    # to this ordering, so a wrong build order would silently flip semantics).
    assert engine.build_fighter_from_player.await_args_list[0].args == (attacker,)
    assert engine.build_fighter_from_player.await_args_list[0].kwargs == {
        "is_attacker": True
    }
    assert engine.build_fighter_from_player.await_args_list[1].args == (defender,)
    assert engine.build_fighter_from_player.await_args_list[1].kwargs == {
        "is_attacker": False
    }
    engine.resolve_combat.assert_called_once()
    assert engine.resolve_combat.call_args.kwargs == {"combat_type": "impart_pk"}
    impart_mgr.transfer_legacy.assert_not_awaited()
    impart_mgr.record_snatch_protection.assert_not_awaited()
    impart_mgr.record_challenge_failure.assert_not_awaited()
    db.update_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_attacker_win_transfers_legacy():
    """An attacker win transfers the instance and grants snatch protection."""
    manager, engine, impart_mgr, _ = _make_deps()
    attacker, defender = _make_player("attacker_1", 1000), _make_player("defender_1")

    ok, battle_text, rewards = await manager.challenge_impart(
        attacker, defender, legacy_type="common"
    )

    assert ok is True
    assert battle_text == "战斗结束"
    impart_mgr.transfer_legacy.assert_awaited_once_with(
        "impart_1", "attacker_1", expected_owner="defender_1"
    )
    impart_mgr.record_snatch_protection.assert_awaited_once_with("defender_1")
    assert rewards["snatched_type"] == "common"
    # legacy_type filter is passed through to target selection.
    impart_mgr.select_snatch_target.assert_awaited_once_with("defender_1", "common")


@pytest.mark.asyncio
async def test_defender_win_penalty_and_exp_clamp():
    """A defender win deducts 1% EXP (int-truncated, clamped at zero)."""
    manager, engine, impart_mgr, db = _make_deps(
        winner_side="fighter2", winner_id="defender_1"
    )
    attacker = _make_player("attacker_1", 1000)

    ok, battle_text, rewards = await manager.challenge_impart(
        attacker, _make_player("defender_1")
    )

    assert ok is False
    assert attacker.experience == 990
    assert rewards["exp_loss"] == 10
    impart_mgr.transfer_legacy.assert_not_awaited()
    impart_mgr.record_challenge_failure.assert_awaited_once_with(
        "attacker_1", "defender_1"
    )
    db.update_player.assert_awaited_once_with(attacker)

    # int() truncation + max(0, ...) clamp: 1999 -> 19, tiny EXP -> 0 loss.
    manager2, _, impart_mgr2, db2 = _make_deps(
        winner_side="fighter2", winner_id="defender_1"
    )
    small = _make_player("attacker_1", 50)
    ok2, _, rewards2 = await manager2.challenge_impart(
        small, _make_player("defender_1")
    )
    assert ok2 is False
    assert small.experience == 50
    assert rewards2["exp_loss"] == 0
    db2.update_player.assert_awaited_once_with(small)

    trunc = _make_player("attacker_1", 1999)
    manager3, _, _, _ = _make_deps(winner_side="fighter2", winner_id="defender_1")
    _, _, rewards3 = await manager3.challenge_impart(trunc, _make_player("defender_1"))
    assert rewards3["exp_loss"] == 19
    assert trunc.experience == 1980


@pytest.mark.asyncio
async def test_transfer_conflict_returns_rejected():
    """A concurrent transfer (transfer_legacy -> None) aborts with a rejection."""
    manager, engine, impart_mgr, _ = _make_deps(transferred=False)

    ok, battle_text, rewards = await manager.challenge_impart(
        _make_player("attacker_1"), _make_player("defender_1")
    )

    assert ok is False
    assert rewards["rejected"].startswith("你慢了一步")
    # The defender must NOT get protection when nothing was actually stolen.
    impart_mgr.record_snatch_protection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setup, expect_substr",
    [
        ("protection", "保护期"),
        ("cooldown", "冷却"),
        ("no_target_default", "没有可夺取的传承"),
        ("no_target_typed", "没有可夺取的common"),
    ],
)
async def test_rejection_branches_skip_combat(setup, expect_substr):
    """Every pre-check rejection returns early without touching the engine."""
    manager, engine, impart_mgr, db = _make_deps()
    if setup == "protection":
        impart_mgr.get_snatch_protection_remaining.return_value = 3600
    elif setup == "cooldown":
        impart_mgr.can_challenge.return_value = (False, 500)
    elif setup == "no_target_default":
        impart_mgr.select_snatch_target.return_value = None
    elif setup == "no_target_typed":
        impart_mgr.select_snatch_target.return_value = None

    kw = {"legacy_type": "common"} if setup == "no_target_typed" else {}
    ok, battle_text, rewards = await manager.challenge_impart(
        _make_player("attacker_1"), _make_player("defender_1"), **kw
    )

    assert ok is False
    assert expect_substr in rewards["rejected"]
    engine.build_fighter_from_player.assert_not_awaited()
    engine.resolve_combat.assert_not_called()
    impart_mgr.transfer_legacy.assert_not_awaited()
    db.update_player.assert_not_awaited()
