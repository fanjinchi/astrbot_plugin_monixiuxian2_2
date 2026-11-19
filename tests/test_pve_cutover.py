"""E2 普通 PVE 切流回归：固定名册默认出怪、难度显式传参、v1 回落。

Covers R2 / implement step 5:
- ``prepare_encounter`` and ``challenge_rift_beast`` default spawns use the
  injected catalog (28 roster reachable) while targeted groups stay unchanged;
- ``pve.difficulty_multiplier`` is passed explicitly from ``game_config``;
- ``catalog=None`` keeps the legacy dynamic path (v1 fallback) and never
  touches guardian-only groups.
"""

import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import PLUGIN_ROOT, load_package_module

_catalog_mod = load_package_module(
    "managers/enemy_catalog.py", "astrbot_plugin_monixiuxian2_2.managers.enemy_catalog"
)
_pve_mod = load_package_module(
    "managers/pve_combat_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.pve_combat_manager",
)
_enemy_mod = load_package_module(
    "managers/enemy_manager.py", "astrbot_plugin_monixiuxian2_2.managers.enemy_manager"
)
_combat_mod = load_package_module(
    "managers/combat_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.combat_manager",
)

EnemyCatalog = _catalog_mod.EnemyCatalog
PVECombatManager = _pve_mod.PVECombatManager
EnemyManager = _enemy_mod.EnemyManager
Enemy = _enemy_mod.Enemy
CombatResult = _combat_mod.CombatResult

ENEMIES_PATH = PLUGIN_ROOT / "config" / "enemies.json"


@pytest.fixture(scope="module")
def catalog():
    """Load the formal v2 config through the real catalog loader."""
    return EnemyCatalog.load(ENEMIES_PATH)


def _player(level: int = 10):
    """Minimal player stub with the fields the PVE manager reads."""
    return SimpleNamespace(user_id="u1", level_index=level, current_hp=100)


def _config(multiplier):
    """Config manager stub exposing the live PvE difficulty knob."""
    return SimpleNamespace(game_config={"pve": {"difficulty_multiplier": multiplier}})


def _manager(catalog_obj, *, enemy_mgr=None, multiplier=1.0):
    engine = MagicMock()
    return PVECombatManager(
        engine,
        enemy_mgr if enemy_mgr is not None else MagicMock(),
        _config(multiplier),
        catalog=catalog_obj,
    )


def test_formal_v2_config_enables_catalog(catalog):
    """The synced formal config loads as a catalog with 28+4 profiles."""
    assert catalog is not None
    assert len(catalog.roster) == 28
    assert len(catalog.world_bosses) == 4


@pytest.mark.parametrize(
    ("level", "category"),
    [
        (1, "normal"),
        (10, "elite"),
        (15, "boss"),
        (30, "normal"),
    ],
)
def test_prepare_encounter_uses_catalog_membership(catalog, level, category):
    """Every default encounter carrier is a roster profile, never a guardian."""
    pve = _manager(catalog)
    pve._should_trigger_combat = lambda *_: True  # noqa: SLF001 - force seam
    pve._select_enemy_category = lambda *_: category  # noqa: SLF001

    prepared = pve.prepare_encounter(_player(level), "adventure", "low")

    assert prepared is not None
    profile = catalog.profile_by_id(prepared.enemy.profile_id)
    assert profile.category == category
    assert not prepared.enemy.user_id.startswith("guardian_")


def test_all_28_roster_entries_reachable_from_default_path(catalog):
    """Frozen RNG: the 28-entry roster is reachable through prepare_encounter."""
    pve = _manager(catalog)
    pve._should_trigger_combat = lambda *_: True  # noqa: SLF001

    seen: set[str] = set()
    saved = random.getstate()
    try:
        random.seed("e2-pve-cutover-roster")
        for level in (1, 10, 20, 30):
            for category in ("normal", "elite", "boss"):
                pve._select_enemy_category = lambda *_args, c=category: c  # noqa: SLF001
                for _ in range(60):
                    prepared = pve.prepare_encounter(_player(level), "adventure", "low")
                    assert prepared is not None
                    seen.add(prepared.enemy.profile_id)
    finally:
        random.setstate(saved)

    assert seen == {profile.id for profile in catalog.roster}


def test_difficulty_multiplier_is_passed_explicitly():
    """The global knob reaches ``catalog.spawn_enemy`` as an explicit kwarg."""
    catalog = MagicMock()
    catalog.spawn_enemy.return_value = Enemy(
        user_id="enemy_x",
        name="妖兽",
        hp=10,
        max_hp=10,
        damage=5,
        agility=1,
        speed=1,
        armor_value=0,
        exp=0,
    )
    pve = _manager(catalog, multiplier=2.5)
    pve._should_trigger_combat = lambda *_: True  # noqa: SLF001
    pve._select_enemy_category = lambda *_: "normal"  # noqa: SLF001

    pve.prepare_encounter(_player(5), "adventure", "low")

    catalog.spawn_enemy.assert_called_once_with(5, "normal", difficulty_multiplier=2.5)


def test_catalog_none_keeps_legacy_dynamic_path():
    """Missing catalog (unsynced/rollback) must not half-cut to the roster."""
    enemy_mgr = MagicMock()
    legacy_enemy = Enemy(
        user_id="guardian_check",
        name="旧妖兽",
        hp=10,
        max_hp=10,
        damage=5,
        agility=1,
        speed=1,
        armor_value=0,
        exp=0,
    )
    enemy_mgr.spawn_enemy.return_value = legacy_enemy
    pve = _manager(None, enemy_mgr=enemy_mgr)
    pve._should_trigger_combat = lambda *_: True  # noqa: SLF001
    pve._select_enemy_category = lambda *_: "normal"  # noqa: SLF001

    prepared = pve.prepare_encounter(_player(5), "adventure", "low")

    assert prepared.enemy is legacy_enemy
    enemy_mgr.spawn_enemy.assert_called_once_with(5, "normal")


def test_legacy_v1_groups_keep_low_mid_high_and_no_guardian_fallback():
    """``low/mid/high`` stay for v1 fallback; guardian never serves normal PvE."""
    manager = EnemyManager(level_config=[{"level": i + 1} for i in range(60)])
    keys = [group.get("key") for group in manager.enemy_groups]
    assert {"low", "mid", "high", "legacy_guardian"} <= set(keys)
    assert "top" not in keys
    assert manager._get_group_by_level(99).get("key") != "legacy_guardian"


@pytest.mark.asyncio
async def test_challenge_rift_beast_default_uses_catalog(catalog):
    """No rift group key: the default rift beast comes from the fixed roster."""
    combat_engine = MagicMock()
    combat_engine.build_fighter_from_player = AsyncMock(return_value=MagicMock())
    combat_engine.resolve_combat.return_value = CombatResult(
        winner_side="fighter1",
        winner_id="u1",
        combat_log=[],
        fighter1_final_hp=90,
        fighter2_final_hp=0,
        rounds=1,
        total_actions=1,
    )
    health = MagicMock()
    health.set_current_hp = AsyncMock(side_effect=lambda _player, hp: hp)
    enemy_mgr = MagicMock()
    pve = PVECombatManager(
        SimpleNamespace(engine=combat_engine),
        enemy_mgr,
        _config(1.0),
        health_service=health,
        catalog=catalog,
    )
    pve._select_enemy_category = lambda *_: "normal"  # noqa: SLF001
    pve._build_enemy_fighter = MagicMock(return_value=MagicMock())  # noqa: SLF001

    result = await pve.challenge_rift_beast(_player(10))

    assert result is not None and result.won is True
    enemy_mgr.spawn_enemy.assert_not_called()
    assert result.enemy_exp == 0  # roster exp placeholder until Step 7


def test_main_wires_one_catalog_before_both_consumers():
    """Static wiring contract: one load, before PVE and world-boss services."""
    source = (PLUGIN_ROOT / "main.py").read_text(encoding="utf-8")
    assert source.count("load_catalog(") == 1
    load_at = source.index("enemy_catalog = load_catalog(")
    assert load_at < source.index("pve_combat_mgr = PVECombatManager(")
    assert load_at < source.index("world_boss_service = WorldBossService(")
    # 旧随机 Boss 生成器与其持久化键不得残留（同一检查点不双跑）
    assert "_schedule_boss_spawn" not in source
    assert "boss_next_spawn_time" not in source
    assert "BossManager" not in source
