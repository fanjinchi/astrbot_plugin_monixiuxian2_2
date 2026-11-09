#!/usr/bin/env python3
"""World-boss HP anchor gate (child D AC9): four profiles x T2 model x real engine.

The four world bosses are a 48h raid wall, not a duel: the T2 reference player
is expected to lose every fight (design pve-enemy-design.md appendix F), so the
HP anchor is derived from the player's expected damage output per attempt:

    HP = per-fight output x 3 (attempts/day) x 2 (days) x gamma (0.75)

Measurement protocol (appendix F v2, 2026-10-10):

- four fixed profiles from design_docs/content-design/world_bosses.csv;
- T2 reference builds for both routes (体修 / 灵修) at the segment entry level
  (1 / 10 / 20 / 30);
- the boss is built through the production mapper
  managers/enemy_catalog.build_enemy_fighter (same path the domain service
  uses) with a placeholder HP large enough that the player always dies;
- three phases measured separately: P1 native, P2 damage x1.1, P3 damage x0.9
  and armor x0.5; per-cell result weighted 40/40/20 by HP share;
- 2000 seeded battles per cell; acceptance = within +/-10% of the frozen
  anchors 228 / 393 / 1035 / 1123 (per-fight output, both routes averaged).

Usage:
    .venv/bin/python design_docs/content-design/sim_world_boss_anchor.py [battles]

Returns:
    Exit code 0 when all four profiles land inside the tolerance band, 1 else.
"""

from __future__ import annotations

import importlib.util
import random
import statistics
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "attribute-growth"))
sys.path.insert(0, str(PLUGIN_ROOT))

from proto_pve_baseline import ENGINE, build_player  # noqa: E402
from tests.helpers import load_package_module  # noqa: E402

# Load the production mapper under the plugin's synthetic package tree so its
# relative imports (core/enemy_schema, combat FighterState) resolve without
# triggering managers/__init__.py's heavy chain.
_catalog_mod = load_package_module(
    "managers/enemy_catalog.py", "astrbot_plugin_monixiuxian2_2.managers.enemy_catalog"
)
EnemyCatalog = _catalog_mod.EnemyCatalog
build_enemy_fighter = _catalog_mod.build_enemy_fighter

BATTLES = int(sys.argv[1]) if len(sys.argv) > 1 else 2000

# Frozen anchors from pve-enemy-design.md appendix F.1 (per-fight output).
ANCHORS = {
    "wb_lq_ba": 228,
    "wb_zj_tuo": 393,
    "wb_jd_zhu": 1035,
    "wb_yy_ba": 1123,
}
TOLERANCE = 0.10
PHASE_WEIGHTS = {1: 0.4, 2: 0.4, 3: 0.2}
ROUTES = ("体修", "灵修")
# Placeholder HP: the boss must survive long enough for the player to fall.
PLACEHOLDER_HP = 10**9


def _load_module(name: str, rel_path: str):
    """Import a plugin module by file path (script is not inside the package).

    Args:
        name: Module name to register in sys.modules.
        rel_path: Path relative to the plugin root.

    Returns:
        The loaded module object.
    """
    path = PLUGIN_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None:
        raise ImportError(f"Cannot find spec for {name} at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_catalog() -> EnemyCatalog:
    """Render the world-boss profiles from the design CSV (draft preview path).

    Returns:
        Catalog whose four world-boss profiles carry the five copy strings and
        are marked narrative-approved for measurement purposes only.
    """
    sync = _load_module("sync_content_to_config", "scripts/sync_content_to_config.py")
    doc, errors = sync.render_enemy_document(
        SCRIPT_DIR, manifest=None, manifest_path=None, existing_config=None
    )
    if errors:
        raise SystemExit(f"敌人名册 preview 生成失败：{errors}")
    for entry in doc["world_bosses"]:
        entry["narrative_approved"] = True
    return EnemyCatalog(doc, source="design preview")


def build_boss_fighter(profile, phase: int):
    """Build one phase-specific boss FighterState through the production mapper.

    Args:
        profile: WorldBossProfile from the catalog.
        phase: 1 (native), 2 (damage x1.1) or 3 (damage x0.9, armor x0.5).

    Returns:
        FighterState for the boss side, placeholder HP so the player dies.
    """
    if phase == 1:
        damage_mult = 1.0
        armor = profile.armor_value
    elif phase == 2:
        damage_mult = profile.phase2_damage_multiplier
        armor = profile.armor_value
    else:
        damage_mult = profile.phase3_damage_multiplier
        armor = round(profile.armor_value * profile.phase3_armor_multiplier)
    # Attribute bag mirroring managers/enemy_manager.Enemy (the mapper only
    # reads these attributes, so no import of the legacy enemy manager).
    enemy = SimpleNamespace(
        user_id="world_boss:" + profile.id,
        name=profile.name,
        hp=PLACEHOLDER_HP,
        max_hp=PLACEHOLDER_HP,
        damage=max(1, round(profile.damage * damage_mult)),
        agility=profile.agility,
        speed=profile.speed,
        armor_value=armor,
        exp=0,
        crit_rate=profile.crit_rate,
        profile_id=profile.id,
        level_index=profile.level_index,
        trigger_skills=[dict(s) for s in profile.trigger_skills],
        ultimates=[dict(u) for u in profile.ultimates],
    )
    return build_enemy_fighter(enemy)


def run_cell(profile, route: str, phase: int, battles: int) -> dict:
    """Run one (profile, route, phase) cell with deterministic per-battle seeding.

    Args:
        profile: WorldBossProfile under test.
        route: T2 reference route (体修 or 灵修).
        phase: Boss phase 1-3.
        battles: Number of seeded battles.

    Returns:
        Mapping with mean damage output, mean rounds and player win rate.
    """
    cell_seed = zlib.crc32(f"{profile.id}|{route}|p{phase}".encode()) % 10**6
    rng = random.Random(cell_seed)
    outputs: list[int] = []
    rounds: list[int] = []
    wins = 0
    for _ in range(battles):
        random.seed(rng.randint(0, 2**31 - 1))
        player = build_player(route, profile.level_index, with_skills=True)
        boss = build_boss_fighter(profile, phase)
        result = ENGINE.resolve_combat(player, boss, combat_type="spar", merge_count=10)
        outputs.append(PLACEHOLDER_HP - result.fighter2_final_hp)
        rounds.append(result.rounds)
        if result.winner_side == "fighter1":
            wins += 1
    return {
        "output": statistics.mean(outputs),
        "rounds": statistics.mean(rounds),
        "win": wins / battles,
    }


def main() -> int:
    """Measure all four profiles and assert the appendix-F anchor band."""
    catalog = load_catalog()
    print(
        f"=== 世界 Boss HP 锚验收：{len(catalog.world_bosses)} 只 x 2 路线 x 3 阶段，"
        f"{BATTLES} 场/格 ==="
    )
    print(f"{'天灾':<10}{'段':<6}{'体重':>7}{'灵重':>7}{'回合':>7}{'胜率':>7}")
    failures: list[str] = []
    for profile in catalog.world_bosses:
        route_outputs = dict.fromkeys(ROUTES, 0.0)
        round_pool: list[float] = []
        win_pool: list[float] = []
        for route in ROUTES:
            weighted = 0.0
            for phase, weight in PHASE_WEIGHTS.items():
                cell = run_cell(profile, route, phase, BATTLES)
                weighted += cell["output"] * weight
                round_pool.append(cell["rounds"])
                win_pool.append(cell["win"])
            route_outputs[route] = weighted
        measured = statistics.mean(route_outputs.values())
        anchor = ANCHORS[profile.id]
        delta = measured / anchor - 1
        ok = abs(delta) <= TOLERANCE
        if not ok:
            failures.append(
                f"{profile.id} 场均输出 {measured:.0f} 偏离锚 {anchor} 达 {delta:+.1%}"
            )
        print(
            f"{profile.name:<10}{profile.segment:<6}"
            f"{route_outputs['体修']:>7.0f}{route_outputs['灵修']:>7.0f}"
            f"{statistics.mean(round_pool):>7.1f}{statistics.mean(win_pool):>7.1%}"
            f"  锚 {anchor} ({delta:+.1%}) {'✓' if ok else '✗'}"
        )
    if failures:
        print(f"\nFAIL {len(failures)}/{len(catalog.world_bosses)} 只出带：")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1
    print(f"\nPASS：{len(catalog.world_bosses)} 只全在 ±{TOLERANCE:.0%} 锚带内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
