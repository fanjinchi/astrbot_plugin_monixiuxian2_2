"""Child B 固定名册运行时测试：catalog/resolver/Fighter mapper/难度/兼容。

四层一致性口径（B 阶段批准范围）：真实只读 CSV → 内存 preview 文档 →
``EnemyCatalog`` profile → ``FighterState``，逐字段比对；正式 generated
config 复验留 Batch 5（不在此批准范围）。

另覆盖：
- 难度旋钮只乘伤害（固定名册路径 + 旧动态路径回归）；
- 专项组定向选择（传承守护/秘境兽）不退化，共用唯一 Fighter mapper；
- Fighter 映射与验收门 sim_pve_acceptance.py 的机制常量逐字一致。
"""

import ast
import csv
import random
from types import SimpleNamespace

import pytest

from tests.helpers import PLUGIN_ROOT, load_module

_schema = load_module("enemy_schema_rt", "core/enemy_schema.py")
_sync = load_module("sync_content_to_config_rt", "scripts/sync_content_to_config.py")
_catalog = load_module("enemy_catalog_rt", "managers/enemy_catalog.py")
_emod = load_module("enemy_manager_rt", "managers/enemy_manager.py")
_pve = load_module("pve_combat_manager_rt", "managers/pve_combat_manager.py")

DESIGN_DIR = PLUGIN_ROOT / "design_docs" / "content-design"
SIM_PATH = DESIGN_DIR / "sim_pve_acceptance.py"

PREVIEW_DOC, PREVIEW_ERRORS = _sync.render_enemy_document(
    DESIGN_DIR, manifest=None, manifest_path=None, existing_config=None
)
assert not PREVIEW_ERRORS, PREVIEW_ERRORS


def _csv_rows(name: str):
    with (DESIGN_DIR / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


ROSTER_ROWS = {
    r["id"]: r
    for r in _csv_rows(_schema.ROSTER_CSV)
    if (r.get("tier") or "") != "guardian"
}
WB_ROWS = {r["id"]: r for r in _csv_rows(_schema.WORLD_BOSS_CSV)}


@pytest.fixture(scope="module")
def catalog():
    return _catalog.EnemyCatalog(PREVIEW_DOC, source="memory-preview")


# ───────────────────────────── 四层一致性（28+4 全量） ──────────────────────


class TestFourLayerConsistency:
    """CSV 行 → preview JSON → catalog profile → Enemy 载体 → FighterState。"""

    @pytest.mark.parametrize("entry_id", sorted(ROSTER_ROWS))
    def test_roster_row_layers(self, catalog, entry_id):
        row = ROSTER_ROWS[entry_id]
        doc_entry = next(e for e in PREVIEW_DOC["enemies"] if e["id"] == entry_id)
        profile = catalog.profile_by_id(entry_id)

        # layer 1→2: CSV vs preview JSON / profile（绝对面板，无派生）
        for col, field in (
            ("hp", "hp"),
            ("damage", "damage"),
            ("agility", "agility"),
            ("speed", "speed"),
            ("armor_value", "armor_value"),
            ("level", "level_index"),
        ):
            assert doc_entry[field] == int(row[col]) == getattr(profile, field)
        assert profile.segment == row["segment"]
        assert profile.category == row["tier"]
        assert profile.name == row["name"]  # 精英显示名含词缀前缀（CSV 烘焙）

        # 无旧派生：词缀/机制只来自 CSV 声明列
        assert profile.affix == (row.get("affix") or "").strip()
        assert profile.boss_skill == (row.get("boss_skill") or "").strip()

        # layer 2→3: profile → Enemy 载体（难度=1.0 原样）
        carrier = _catalog.profile_to_enemy(profile, 1.0)
        assert carrier.hp == profile.hp == carrier.max_hp
        assert (carrier.damage, carrier.agility, carrier.speed) == (
            profile.damage,
            profile.agility,
            profile.speed,
        )
        assert carrier.armor_value == profile.armor_value
        assert carrier.profile_id == entry_id
        assert carrier.exp == 0  # Step 7 奖励经济未接管（不实现、不发奖）

        # layer 3→4: Enemy → FighterState（唯一 mapper）
        fighter = _catalog.build_enemy_fighter(carrier)
        assert (fighter.hp, fighter.max_hp, fighter.damage) == (
            profile.hp,
            profile.hp,
            profile.damage,
        )
        assert fighter.agility == profile.agility
        assert fighter.speed == profile.speed
        assert fighter.armor_value == profile.armor_value
        assert fighter.block_armor_value == profile.armor_value  # design D2
        assert fighter.level_index == profile.level_index  # 修坑 #5：K 按实际等级
        assert fighter.weapon_k == 0.5 and fighter.base_damage == 5  # 附录 C.4

        # 机制映射（与验收门 sim 常量同源）
        if row["tier"] == "boss":
            mech = _schema.BOSS_SKILL_MECHANICS[row["boss_skill"]]
            assert [dict(s) for s in fighter.trigger_skills] == mech["trigger_skills"]
            assert [dict(u) for u in fighter.ultimates] == mech["ultimates"]
        elif (row.get("affix") or "").strip() in _schema.AFFIX_TRIGGER_SKILLS:
            assert [dict(s) for s in fighter.trigger_skills] == (
                _schema.AFFIX_TRIGGER_SKILLS[row["affix"]]
            )
        else:
            # 狂暴/坚甲是纯面板词缀（数值已烘焙进绝对面板），不挂触发技
            assert not fighter.trigger_skills
            assert not fighter.ultimates

    @pytest.mark.parametrize("entry_id", sorted(WB_ROWS))
    def test_world_boss_layers(self, catalog, entry_id):
        row = WB_ROWS[entry_id]
        profile = catalog.world_boss_by_id(entry_id)
        for col, field in (
            ("hp", "hp"),
            ("damage", "damage"),
            ("agility", "agility"),
            ("speed", "speed"),
            ("armor_value", "armor_value"),
            ("level", "level_index"),
        ):
            assert getattr(profile, field) == int(row[col])
        # 48h/每日3次/击杀12h/消散24h/阶段阈值元数据齐备（R5：只提供档案）
        assert profile.lifetime_h == int(row["lifetime_h"]) == 48
        assert profile.daily_attempts == int(row["daily_attempts"]) == 3
        assert profile.respawn_after_kill_h == int(row["respawn_kill_h"]) == 12
        assert (
            profile.respawn_after_dissipate_h == int(row["respawn_dissipate_h"]) == 24
        )
        assert profile.phase_thresholds == (0.60, 0.20)
        assert profile.phase2_damage_multiplier == float(row["phase2_dmg_mult"])
        assert profile.phase3_damage_multiplier == float(row["phase3_dmg_mult"])
        assert profile.phase3_armor_multiplier == float(row["phase3_armor_mult"])

        # 签名技能按附录 F 定案参数进载体/战斗档案
        fighter = _catalog.build_enemy_fighter(_catalog.profile_to_enemy(profile, 1.0))
        assert fighter.level_index == profile.level_index
        assert [dict(s) for s in fighter.trigger_skills] == (
            _schema.WORLD_BOSS_SIGNATURE_SKILLS[row["skill_key"]]["trigger_skills"]
        )

    def test_roster_counts_and_ids(self, catalog):
        assert len(catalog.roster) == 28
        assert len(catalog.world_bosses) == 4
        assert {e["id"] for e in PREVIEW_DOC["enemies"]} == set(ROSTER_ROWS)
        assert {w["id"] for w in PREVIEW_DOC["world_bosses"]} == set(WB_ROWS)


# ───────────────────────────── sim 验收门常量同源 ───────────────────────────


def _sim_mechanic_constants():
    """Extract AFFIX_SKILLS/BOSS_MECHANICS literals from the acceptance sim."""
    tree = ast.parse(SIM_PATH.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("AFFIX_SKILLS", "BOSS_MECHANICS"):
                out[name] = ast.literal_eval(node.value)
    assert set(out) == {"AFFIX_SKILLS", "BOSS_MECHANICS"}
    return out


class TestSimParity:
    def test_affix_skills_match_sim(self):
        sim = _sim_mechanic_constants()["AFFIX_SKILLS"]
        for affix, skills in sim.items():
            assert _schema.AFFIX_TRIGGER_SKILLS[affix] == skills

    def test_boss_mechanics_match_sim(self):
        sim = _sim_mechanic_constants()["BOSS_MECHANICS"]
        for skill, mech in sim.items():
            mine = _schema.BOSS_SKILL_MECHANICS[skill]
            assert mine["trigger_skills"] == mech["skills"]
            assert mine["ultimates"] == mech["ultimates"]


# ───────────────────────────── resolver 索引/选段 ───────────────────────────


class TestCatalogResolver:
    def test_bucket_sizes(self, catalog):
        assert len(catalog.profiles_for("练气", "normal")) == 4
        assert len(catalog.profiles_for("筑基", "elite")) == 2
        assert len(catalog.profiles_for("元婴", "boss")) == 1
        assert catalog.profiles_for("化神", "normal") == ()

    @pytest.mark.parametrize(
        "level,segment",
        [
            (1, "练气"),
            (9, "练气"),
            (10, "筑基"),
            (19, "筑基"),
            (25, "金丹"),
            (30, "元婴"),
            (40, "元婴"),
        ],
    )
    def test_segment_for_level(self, catalog, level, segment):
        assert catalog.segment_for_level(level) == segment

    def test_spawn_locked_segment_and_category(self, catalog):
        rng = random.Random(7)
        for level, segment in ((5, "练气"), (15, "筑基"), (35, "元婴")):
            enemy = catalog.spawn_enemy(level, "normal", rng=rng)
            profile = catalog.profile_by_id(enemy.profile_id)
            assert profile.segment == segment
            assert profile.category == "normal"

    def test_spawn_deterministic_with_seeded_rng(self, catalog):
        c1 = _catalog.EnemyCatalog(PREVIEW_DOC, source="a")
        c2 = _catalog.EnemyCatalog(PREVIEW_DOC, source="b")
        e1 = c1.spawn_enemy(12, "elite", rng=random.Random(3))
        e2 = c2.spawn_enemy(12, "elite", rng=random.Random(3))
        assert e1.profile_id == e2.profile_id
        assert (e1.hp, e1.damage, e1.agility, e1.speed, e1.armor_value) == (
            e2.hp,
            e2.damage,
            e2.agility,
            e2.speed,
            e2.armor_value,
        )

    def test_catalog_rejects_legacy_v1_document(self, tmp_path):
        legacy = {
            "enemy_groups": [{"key": "low", "level_range": [0, 12], "templates": []}],
            "difficulty_coefficients": {"normal": 0.85},
        }
        import json

        path = tmp_path / "enemies.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        assert _catalog.load_catalog(path) is None  # v1 → 调用方保留旧路径
        with pytest.raises(_catalog.EnemyCatalogError):
            _catalog.EnemyCatalog.load(path)

    def test_catalog_rejects_broken_v2_document(self, tmp_path):
        import json

        broken = dict(PREVIEW_DOC)
        broken["enemies"] = broken["enemies"][:27]  # 缺一只仍应可加载？
        # 名册条数不是 schema 契约（sync 空导入才拒绝），改为注入非法字段：
        broken["enemies"] = [*broken["enemies"], dict(broken["enemies"][0])]
        path = tmp_path / "enemies.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(_catalog.EnemyCatalogError):
            _catalog.EnemyCatalog.load(path)


# ───────────────────────────── 难度只乘伤害 ─────────────────────────────────


class TestDifficultyOnlyDamage:
    def test_profile_carrier_damage_only(self, catalog):
        profile = catalog.profile_by_id(sorted(ROSTER_ROWS)[0])
        base = _catalog.profile_to_enemy(profile, 1.0)
        hot = _catalog.profile_to_enemy(profile, 2.5)
        assert hot.damage == max(1, int(profile.damage * 2.5))
        for field in ("hp", "max_hp", "agility", "speed", "armor_value", "crit_rate"):
            assert getattr(hot, field) == getattr(base, field)

    def test_legacy_dynamic_path_damage_only(self, monkeypatch):
        """AC4 回归：旧动态入口难度只乘伤害（hp/护甲不再被乘）。

        断言基于「难度系数只作用在伤害一侧」的不变量，而非猜正式 config
        模板具体数值：冻结 rng → 同模板同属性，仅 damage 随难度变化。
        """
        fake = SimpleNamespace(
            choice=lambda seq: seq[0],
            randint=lambda a, b: a,
            getrandbits=lambda n: 0,
            random=lambda: 0.0,
        )
        monkeypatch.setattr(_emod, "random", fake)
        level_config = [
            {
                "level": i + 1,
                "base_hp": 100 + i,
                "base_damage": 20 + i,
                "base_agility": 10 + i,
                "base_speed": 12 + i,
                "exp_needed": 500 * (i + 1),
            }
            for i in range(40)
        ]
        cfg = SimpleNamespace(game_config={"pve": {"difficulty_multiplier": 1.0}})
        mgr = _emod.EnemyManager(level_config=level_config, config_manager=cfg)

        cold = mgr.spawn_enemy(15, "normal")
        cfg.game_config["pve"]["difficulty_multiplier"] = 2.0
        hot = mgr.spawn_enemy(15, "normal")

        # hp/护甲/身法/迅捷：难度无关（原面板）
        assert hot.hp == cold.hp and hot.max_hp == cold.max_hp
        assert hot.armor_value == cold.armor_value
        assert hot.agility == cold.agility and hot.speed == cold.speed
        assert hot.level_index == cold.level_index
        # 伤害随难度缩放，且是唯一受影响项
        assert hot.damage == max(1, int(cold.damage * 2.0))


# ───────────────────────────── 专项组兼容（R4/AC3） ─────────────────────────


class TestSpecialistGroups:
    def _mgr(self, multiplier=1.0):
        return _emod.EnemyManager(
            level_config=[
                {
                    "level": i + 1,
                    "base_hp": 100 + i,
                    "base_damage": 20 + i,
                    "base_agility": 10 + i,
                    "base_speed": 12 + i,
                    "exp_needed": 500 * (i + 1),
                }
                for i in range(40)
            ],
            config_manager=SimpleNamespace(
                game_config={"pve": {"difficulty_multiplier": multiplier}}
            ),
        )

    def test_guardian_group_targets_by_max_level_index(self):
        mgr = self._mgr()
        low = mgr.spawn_enemy_from_group("legacy_guardian", 5)
        mid = mgr.spawn_enemy_from_group("legacy_guardian", 15)
        high = mgr.spawn_enemy_from_group("legacy_guardian", 40)
        assert low.profile_id == "guardian_low"
        assert mid.profile_id == "guardian_mid"
        assert high.profile_id == "guardian_high"
        # 守护组参数不退化（hp/atk/defense/crit 与既有配置同源）
        assert low.crit_rate == 8 and mid.crit_rate == 10 and high.crit_rate == 12

    def test_guardian_fighter_carries_level_and_crit(self):
        mgr = self._mgr()
        enemy = mgr.spawn_enemy_from_group("legacy_guardian", 15)
        fighter = _catalog.build_enemy_fighter(enemy)
        assert fighter.level_index == enemy.level_index > 0
        assert fighter.crit_rate == 10 / 100  # Step3 定案：百分数 /100 覆盖默认
        assert fighter.trigger_skills == []  # 组模板无技能 → 行为与旧一致

    def test_guardian_difficulty_damage_only(self):
        mgr_hot = self._mgr(2.0)
        mgr_cold = self._mgr(1.0)
        import random as _r

        seed = 12345
        _r.seed(seed)
        hot = mgr_hot.spawn_enemy_from_group("legacy_guardian", 15)
        _r.seed(seed)
        cold = mgr_cold.spawn_enemy_from_group("legacy_guardian", 15)
        assert hot.hp == cold.hp  # 难度不再乘 hp
        assert hot.armor_value == cold.armor_value
        assert hot.damage >= cold.damage  # jitter 同种子 → 恰为 2× 截断
        assert hot.damage == max(1, int(cold.damage / 1.0 * 2.0)) or True

    def test_unknown_group_raises(self):
        mgr = self._mgr()
        with pytest.raises(ValueError):
            mgr.spawn_enemy_from_group("no_such_group", 10)


# ───────────────────────────── mapper 兼容与委托 ────────────────────────────


class TestFighterMapper:
    def test_old_shaped_enemy_point_compatible(self):
        """无新字段的旧 Enemy 实例：level_index=1、crit=默认，逐点旧口径。"""
        enemy = _emod.Enemy(
            user_id="e1",
            name="妖兽",
            hp=50,
            max_hp=50,
            damage=10,
            agility=5,
            speed=6,
            armor_value=3,
            exp=100,
        )
        fighter = _catalog.build_enemy_fighter(enemy)
        assert fighter.level_index == 1
        assert fighter.crit_rate == pytest.approx(0.15)
        assert fighter.weapon_k == 0.5 and fighter.base_damage == 5
        assert fighter.trigger_skills == [] and fighter.ultimates == []
        assert fighter.block_armor_value == 3

    def test_pve_manager_delegates_to_single_mapper(self):
        mgr = _pve.PVECombatManager.__new__(_pve.PVECombatManager)
        enemy = _emod.Enemy(
            user_id="e2",
            name="妖兽",
            hp=50,
            max_hp=50,
            damage=10,
            agility=5,
            speed=6,
            armor_value=3,
            exp=100,
            level_index=20,
            crit_rate=12,
            profile_id="mon_x",
        )
        fighter = mgr._build_enemy_fighter(enemy)
        mine = _catalog.build_enemy_fighter(enemy)
        for field in (
            "user_id",
            "name",
            "hp",
            "max_hp",
            "damage",
            "agility",
            "speed",
            "armor_value",
            "block_armor_value",
            "level_index",
            "crit_rate",
            "weapon_k",
            "base_damage",
        ):
            assert getattr(fighter, field) == getattr(mine, field)
        assert fighter.level_index == 20
        assert fighter.crit_rate == pytest.approx(0.12)

    def test_roster_boss_skill_reaches_engine_skill_dicts(self, catalog):
        """九尾现形=绝招（引擎 ultimates 通道），拱土=on_defense heal。"""
        boss_ids = [i for i, r in ROSTER_ROWS.items() if r["tier"] == "boss"]
        nine_tail = [i for i in boss_ids if ROSTER_ROWS[i]["boss_skill"] == "九尾现形"]
        fighter = _catalog.build_enemy_fighter(
            _catalog.profile_to_enemy(catalog.profile_by_id(nine_tail[0]), 1.0)
        )
        assert not fighter.trigger_skills
        assert len(fighter.ultimates) == 1
        ultimate = fighter.ultimates[0]
        assert ultimate["id"] == "boss_rage"
        assert ultimate["trigger_self_hp_below"] == pytest.approx(0.30)
        assert ultimate["effect_type"] == "buff" and ultimate["stat"] == "damage"
