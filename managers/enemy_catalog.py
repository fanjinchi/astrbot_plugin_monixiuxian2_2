# managers/enemy_catalog.py
"""固定敌人名册运行时：不可变 catalog、段位 resolver 与统一 Fighter 映射。

Trellis 10-10-pve-enemy-catalog-runtime（Child B）交付物之一：
28 只名册敌人 + 4 只世界 Boss 的 combat profile 由
``scripts/sync_content_to_config.py`` 从 design_docs 名册 CSV 渲染进
``config/enemies.json``（schema_version=2），本模块负责加载、校验、索引与
到 ``FighterState`` 的唯一映射。名册数值是设计段位绝对面板——无
exp_needed 派生、无随机等级、无类别倍率、无 ±10% 抖动（R2/AC2）；
``pve.difficulty_multiplier`` 只在 ``spawn_enemy`` 单点乘伤害。

Child B 不切调用方：本模块不写库、不发奖、不接冒险/秘境生命周期
（Batch 5 切流、Child C/D 接管）。世界 Boss 仅提供不可变 profile 与
copy-to-snapshot 输入，实例化/消散属 Child D。
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from astrbot.api import logger
except ImportError:  # 独立测试环境无 astrbot
    import logging

    logger = logging.getLogger("enemy_catalog")

try:
    from ..core.enemy_schema import SCHEMA_VERSION, validate_enemy_document
    from .combat_manager import FighterState
    from .enemy_manager import Enemy
except ImportError:
    # 独立运行（测试）：load_module 绕过包 __init__ 链，相对导入不可用，
    # 与 pve_combat_manager 同款降级装载。
    import importlib.util
    import os
    import sys

    def _standalone(name: str, rel_path: str):
        """Load a plugin module by file path without its package __init__."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    _schema = _standalone("enemy_catalog_schema", "core/enemy_schema.py")
    SCHEMA_VERSION = _schema.SCHEMA_VERSION
    validate_enemy_document = _schema.validate_enemy_document
    _cm = _standalone("enemy_catalog_combat", "managers/combat_manager.py")
    FighterState = _cm.FighterState
    _em = _standalone("enemy_catalog_enemy", "managers/enemy_manager.py")
    Enemy = _em.Enemy

__all__ = [
    "EnemyCatalog",
    "EnemyCatalogError",
    "EnemyCombatProfile",
    "WorldBossProfile",
    "build_enemy_fighter",
    "profile_to_enemy",
]


class EnemyCatalogError(ValueError):
    """固定名册 catalog 拒绝加载/解析时的 fail-closed 错误。"""


@dataclass(frozen=True)
class EnemyCombatProfile:
    """单只名册敌人的不可变战斗档案（schema PROFILE_VERSION=1 字段集）。

    Attributes:
        id: 名册稳定 id（enemies.csv ``id`` 列）。
        name: 完整显示名（精英含词缀前缀，CSV 已烘焙）。
        segment: 境界段（练气/筑基/金丹/元婴）。
        category: 档位（normal/elite/boss）。
        archetype: 原型标签（均衡/坚壳/猛击/迅捷，仅溯源展示）。
        level_index: 设计等级（1-based，进 FighterState.level_index）。
        level_range: 服务等级闭区间 (low, high)，1-based。
        hp: 气血绝对值。
        damage: 伤害绝对值。
        agility: 身法绝对值。
        speed: 迅捷绝对值。
        armor_value: 护甲绝对值。
        crit_rate: 暴击率（百分数原值；0 表示用引擎基础暴击率）。
        affix: 精英词缀名（否则空串）。
        boss_skill: Boss 机制名（否则空串）。
        trigger_skills: 触发技 dict 元组（sync 物化产物）。
        ultimates: 绝招 dict 元组。
        exp: 修为奖励占位（Step 7 奖励经济接管前恒 0）。
    """

    id: str
    name: str
    segment: str
    category: str
    archetype: str
    level_index: int
    level_range: tuple[int, int]
    hp: int
    damage: int
    agility: int
    speed: int
    armor_value: int
    crit_rate: float
    affix: str
    boss_skill: str
    trigger_skills: tuple[dict, ...]
    ultimates: tuple[dict, ...]
    exp: int
    status: str
    narrative_status: str

    @classmethod
    def from_dict(cls, entry: dict) -> EnemyCombatProfile:
        """Build a frozen profile from one generated ``enemies`` entry.

        Args:
            entry: validated config entry dict (schema v2 shape).

        Returns:
            Immutable combat profile with copied skill dicts.
        """
        return cls(
            id=entry["id"],
            name=entry["name"],
            segment=entry["segment"],
            category=entry["category"],
            archetype=entry.get("archetype", ""),
            level_index=int(entry["level_index"]),
            level_range=(int(entry["level_range"][0]), int(entry["level_range"][1])),
            hp=int(entry["hp"]),
            damage=int(entry["damage"]),
            agility=int(entry["agility"]),
            speed=int(entry["speed"]),
            armor_value=int(entry["armor_value"]),
            crit_rate=float(entry["crit_rate"]),
            affix=entry.get("affix", ""),
            boss_skill=entry.get("boss_skill", ""),
            trigger_skills=tuple(dict(s) for s in entry.get("trigger_skills", [])),
            ultimates=tuple(dict(u) for u in entry.get("ultimates", [])),
            exp=int(entry.get("exp", 0)),
            status=entry.get("status", ""),
            narrative_status=entry.get("narrative_status", ""),
        )


@dataclass(frozen=True)
class WorldBossProfile:
    """单只世界 Boss 的不可变战斗+元数据档案（Child D 只做输入，不做实例）。

    Attributes:
        id / name / segment / level_index / hp / damage / agility / speed /
        armor_value / crit_rate: 同 :class:`EnemyCombatProfile` 语义。
        signature_skill: 招牌技显示名（world_bosses.csv）。
        skill_key: 招牌技机制 key（连咬/反震/灼烧/绞杀）。
        trigger_skills / ultimates: 物化技能元组。
        phase_thresholds: (P2, P3) HP 占比降序阈值。
        phase2_damage_multiplier: P2 伤害倍率。
        phase3_damage_multiplier: P3 伤害倍率。
        phase3_armor_multiplier: P3 护甲倍率。
        lifetime_h / daily_attempts / respawn_after_kill_h /
        respawn_after_dissipate_h: 刷新/消散元数据（小时/次数）。
    """

    id: str
    name: str
    segment: str
    level_index: int
    hp: int
    damage: int
    agility: int
    speed: int
    armor_value: int
    crit_rate: float
    signature_skill: str
    skill_key: str
    trigger_skills: tuple[dict, ...]
    ultimates: tuple[dict, ...]
    phase_thresholds: tuple[float, float]
    phase2_damage_multiplier: float
    phase3_damage_multiplier: float
    phase3_armor_multiplier: float
    lifetime_h: int
    daily_attempts: int
    respawn_after_kill_h: int
    respawn_after_dissipate_h: int
    status: str
    narrative_status: str

    @classmethod
    def from_dict(cls, entry: dict) -> WorldBossProfile:
        """Build a frozen profile from one generated ``world_bosses`` entry.

        Args:
            entry: validated config entry dict (schema v2 shape).

        Returns:
            Immutable world-boss profile with copied skill dicts.
        """
        return cls(
            id=entry["id"],
            name=entry["name"],
            segment=entry["segment"],
            level_index=int(entry["level_index"]),
            hp=int(entry["hp"]),
            damage=int(entry["damage"]),
            agility=int(entry["agility"]),
            speed=int(entry["speed"]),
            armor_value=int(entry["armor_value"]),
            crit_rate=float(entry["crit_rate"]),
            signature_skill=entry.get("signature_skill", ""),
            skill_key=entry["skill_key"],
            trigger_skills=tuple(dict(s) for s in entry.get("trigger_skills", [])),
            ultimates=tuple(dict(u) for u in entry.get("ultimates", [])),
            phase_thresholds=(
                float(entry["phase_thresholds"][0]),
                float(entry["phase_thresholds"][1]),
            ),
            phase2_damage_multiplier=float(entry["phase2_damage_multiplier"]),
            phase3_damage_multiplier=float(entry["phase3_damage_multiplier"]),
            phase3_armor_multiplier=float(entry["phase3_armor_multiplier"]),
            lifetime_h=int(entry["lifetime_h"]),
            daily_attempts=int(entry["daily_attempts"]),
            respawn_after_kill_h=int(entry["respawn_after_kill_h"]),
            respawn_after_dissipate_h=int(entry["respawn_after_dissipate_h"]),
            status=entry.get("status", ""),
            narrative_status=entry.get("narrative_status", ""),
        )


def profile_to_enemy(
    profile: EnemyCombatProfile | WorldBossProfile,
    difficulty_multiplier: float = 1.0,
    user_id_prefix: str = "enemy",
    seq: int = 0,
    token: int = 0,
) -> Enemy:
    """Instantiate one immutable combat profile into a battle-carrier ``Enemy``.

    绝对面板原样拷贝；``difficulty_multiplier`` **只乘伤害**（R2；与旧
    spawn_enemy 同用 int 截断口径）。技能元组逐字段 deepcopy 成列表，
    catalog 的不可变档案永不被战斗侧写脏。

    Args:
        profile: roster or world-boss combat profile.
        difficulty_multiplier: ``pve.difficulty_multiplier`` live knob.
        user_id_prefix: carrier id namespace ("enemy"/"world_boss").
        seq: monotonic spawn counter for unique user ids.
        token: per-spawn random token for unique user ids.

    Returns:
        Enemy carrier with level_index/crit/skills fully populated for
        :func:`build_enemy_fighter`.
    """
    damage = max(1, int(profile.damage * difficulty_multiplier))
    exp = int(getattr(profile, "exp", 0) or 0)
    return Enemy(
        user_id=f"{user_id_prefix}_{profile.id}_{seq}_{token:04x}",
        name=profile.name,
        hp=profile.hp,
        max_hp=profile.hp,
        damage=damage,
        agility=profile.agility,
        speed=profile.speed,
        armor_value=profile.armor_value,
        exp=exp,
        crit_rate=profile.crit_rate,
        # 兼容旧字段（与动态路径同构，下游读取点不变）
        mp=exp,
        max_mp=exp,
        atk=damage,
        defense=profile.armor_value,
        profile_id=profile.id,
        level_index=profile.level_index,
        affix=profile.affix if isinstance(profile, EnemyCombatProfile) else "",
        boss_skill=(
            profile.boss_skill if isinstance(profile, EnemyCombatProfile) else ""
        ),
        trigger_skills=[dict(s) for s in profile.trigger_skills],
        ultimates=[dict(u) for u in profile.ultimates],
    )


def build_enemy_fighter(enemy: Enemy) -> FighterState:
    """Enemy → FighterState 的唯一映射（名册/动态/专项组共用，R3）。

    映射口径与验收门 design_docs/content-design/sim_pve_acceptance.py
    ``build_monster`` 逐字段一致：

    - 妖兽空手：``weapon_k=0.5``、``base_damage=5``（附录 C.4；与引擎
      缺省回退数值相同，显式写入保证字段级一致）。
    - ``block_armor_value`` 等同天生护甲全额进格挡（design D2）。
    - ``level_index`` 透传（修坑 #5：护甲减伤 K=100+10×守方等级不再
      恒按 1 计）；未携带（旧 Enemy 实例，0）保持引擎默认 1，行为逐点不变。
    - ``crit_rate`` >0 时按百分数 /100 覆盖引擎基础暴击率（Step3 定案，
      修坑 #3）；0/缺省保持默认。
    - trigger_skills/ultimates 原样传入（修坑：Boss 机制此前不进战斗）。

    Args:
        enemy: any enemy carrier (roster-spawned or legacy dynamic).

    Returns:
        FighterState ready for ``CombatEngine.resolve_combat``.
    """
    kwargs: dict[str, Any] = {
        "user_id": enemy.user_id,
        "name": enemy.name,
        "hp": enemy.hp,
        "max_hp": enemy.max_hp,
        "damage": enemy.damage,
        "agility": enemy.agility,
        "speed": enemy.speed,
        "armor_value": enemy.armor_value,
        # PvE 敌人护甲语义等同天生护甲，全额参与格挡（design D2）；
        # getattr 回退兑现「敌可携 block_armor_value 覆盖」的契约。
        "block_armor_value": getattr(enemy, "block_armor_value", enemy.armor_value),
        "weapon_k": 0.5,
        "base_damage": 5,
    }
    level_index = getattr(enemy, "level_index", 0)
    if level_index > 0:
        kwargs["level_index"] = level_index
    crit_rate = getattr(enemy, "crit_rate", 0) or 0
    if crit_rate > 0:
        # 名册/组模板存百分数原值（8 = 8%）；FighterState 用小数。
        kwargs["crit_rate"] = crit_rate / 100.0
    skills = getattr(enemy, "trigger_skills", None)
    if skills:
        kwargs["trigger_skills"] = [dict(s) for s in skills]
    ultimates = getattr(enemy, "ultimates", None)
    if ultimates:
        kwargs["ultimates"] = [dict(u) for u in ultimates]
    return FighterState(**kwargs)


class EnemyCatalog:
    """固定名册不可变 catalog：(境界段, 档位) 索引 + 段位 resolver。

    加载即全量校验（:func:`core.enemy_schema.validate_enemy_document`），
    任何契约错误 fail-closed 抛 :class:`EnemyCatalogError`——运行时永远
    不会消费半旧半新的混合格式。

    Attributes:
        meta: 文档审计头（schema/profile 版本、来源 CSV hash 等）。
    """

    def __init__(self, doc: dict, source: str = ""):
        """Validate a schema-v2 document and build immutable indexes.

        Args:
            doc: parsed ``config/enemies.json`` v2 document.
            source: origin label for error messages (usually the path).

        Raises:
            EnemyCatalogError: any contract validation error.
        """
        errors = validate_enemy_document(doc)
        if errors:
            raise EnemyCatalogError(
                f"敌人名册配置校验失败（{source or '内存文档'}）：{errors[:6]}"
            )
        self.meta = {
            "schema_version": doc.get("schema_version"),
            "profile_version": doc.get("profile_version"),
            "source": doc.get("source", {}),
        }
        self.roster: tuple[EnemyCombatProfile, ...] = tuple(
            EnemyCombatProfile.from_dict(e) for e in doc["enemies"]
        )
        self.world_bosses: tuple[WorldBossProfile, ...] = tuple(
            WorldBossProfile.from_dict(b) for b in doc["world_bosses"]
        )
        # WB id 走独立命名空间（world_boss_by_id），与名册 id 不互查
        self._by_id: dict[str, EnemyCombatProfile] = {p.id: p for p in self.roster}
        self._wb_by_id: dict[str, WorldBossProfile] = {
            b.id: b for b in self.world_bosses
        }
        # (realm_segment, category) 索引：同段同档内随机抽取即名册语义
        self._index: dict[tuple[str, str], tuple[EnemyCombatProfile, ...]] = {}
        for p in self.roster:
            key = (p.segment, p.category)
            self._index.setdefault(key, [])
            self._index[key] = (*self._index[key], p)
        # 段位服务区间：各 segment 的 level_range 并集（名册 CSV 保证同段一致）
        bands: dict[str, list[int]] = {}
        for p in self.roster:
            lo, hi = bands.setdefault(p.segment, [p.level_range[0], p.level_range[1]])
            bands[p.segment] = [min(lo, p.level_range[0]), max(hi, p.level_range[1])]
        self._segment_bands: list[tuple[str, int, int]] = sorted(
            (seg, r[0], r[1]) for seg, r in bands.items()
        )
        self._spawn_seq = 0

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: Path) -> EnemyCatalog:
        """Load and validate a v2 roster document from disk.

        Args:
            path: config/enemies.json（或测试临时 preview）路径。

        Returns:
            Ready immutable catalog.

        Raises:
            EnemyCatalogError: file unreadable or contract-invalid（含
                v1 旧格式——需经 sync 重新生成，Batch 5 切流）。
        """
        try:
            doc = cls.read_document(path)
        except OSError as exc:
            raise EnemyCatalogError(f"敌人名册配置读取失败：{exc}") from exc
        return cls(doc, source=str(path))

    @staticmethod
    def read_document(path: Path) -> dict:
        """Read and JSON-parse a roster config document.

        Args:
            path: config file path.

        Returns:
            Parsed document dict.

        Raises:
            EnemyCatalogError: JSON invalid or document not a dict.
            OSError: file missing/unreadable (caller maps to fallback).
        """
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise EnemyCatalogError("敌人名册配置必须是 JSON 对象")
        return doc

    def is_fixed_roster(self) -> bool:
        """Return True when the document carries the v2 fixed-roster schema."""
        return self.meta.get("schema_version") == SCHEMA_VERSION

    # ---------------------------------------------------------------- queries

    def profiles_for(self, segment: str, category: str) -> tuple:
        """Return the roster tuple for one (segment, category) bucket.

        Args:
            segment: realm segment label (练气/筑基/金丹/元婴).
            category: normal/elite/boss.

        Returns:
            Tuple of matching profiles; empty when the bucket is absent.
        """
        return self._index.get((segment, category), ())

    def profile_by_id(self, entry_id: str) -> EnemyCombatProfile:
        """Look up one roster profile by stable id.

        Args:
            entry_id: enemies.csv id column value.

        Returns:
            The frozen profile.

        Raises:
            EnemyCatalogError: unknown id.
        """
        profile = self._by_id.get(entry_id)
        if profile is None:
            raise EnemyCatalogError(f"未知的名册敌人 id: {entry_id}")
        return profile

    def world_boss_by_id(self, entry_id: str) -> WorldBossProfile:
        """Look up one world-boss profile by stable id.

        Args:
            entry_id: world_bosses.csv id column value.

        Returns:
            The frozen profile.

        Raises:
            EnemyCatalogError: unknown id.
        """
        profile = self._wb_by_id.get(entry_id)
        if profile is None:
            raise EnemyCatalogError(f"未知的世界 Boss id: {entry_id}")
        return profile

    def segment_for_level(self, player_level: int) -> str:
        """Map a player level to its serving roster segment.

        区间外侧夹取（低→首段，高→末段），与旧动态分组越界回退语义一致。

        Args:
            player_level: player's level_index (1-based).

        Returns:
            Segment label of the band containing/nearest the level.

        Raises:
            EnemyCatalogError: catalog has no roster entries (impossible
                after validation, kept as a guard).
        """
        if not self._segment_bands:
            raise EnemyCatalogError("名册为空")
        for seg, lo, hi in self._segment_bands:
            if lo <= player_level <= hi:
                return seg
        if player_level < self._segment_bands[0][1]:
            return self._segment_bands[0][0]
        return self._segment_bands[-1][0]

    # ---------------------------------------------------------------- spawn

    def spawn_enemy(
        self,
        player_level: int,
        category: str,
        difficulty_multiplier: float = 1.0,
        rng: random.Random = random,
    ) -> Enemy:
        """Instantiate one roster enemy for the encounter request.

        与旧 ``EnemyManager.spawn_enemy`` 同名同参，便于 Batch 5 切流；
        差异即本 child 的存在意义：面板取设计段位绝对值，无随机等级/
        类别倍率/±10% 抖动，难度系数只乘伤害（R2/AC5）。

        Args:
            player_level: 玩家等级，决定服务段位。
            category: "normal" / "elite" / "boss"。
            difficulty_multiplier: game_config ``pve.difficulty_multiplier``。
            rng: injectable randomness source (tests freeze seeds).

        Returns:
            Enemy carrier ready for :func:`build_enemy_fighter`.

        Raises:
            EnemyCatalogError: 段位/档位组合在名册中不存在。
        """
        segment = self.segment_for_level(player_level)
        pool = self.profiles_for(segment, category)
        if not pool:
            raise EnemyCatalogError(f"名册缺少 {segment}/{category} 敌人")
        profile = rng.choice(pool)
        self._spawn_seq += 1
        enemy = profile_to_enemy(
            profile,
            difficulty_multiplier=difficulty_multiplier,
            seq=self._spawn_seq,
            token=rng.getrandbits(16),
        )
        return enemy


def load_catalog(
    path: Path, difficulty_provider: Callable[[], float] | None = None
) -> EnemyCatalog | None:
    """Best-effort catalog loader for future call-site wiring.

    Args:
        path: enemies config path.
        difficulty_provider: reserved hook for the live multiplier knob
            (Batch 5 切流时由装配段注入；Child B 不接调用方).

    Returns:
        EnemyCatalog when the file holds a valid v2 document, else None
        (missing/legacy v1 file → caller keeps the legacy dynamic path).
    """
    try:
        catalog = EnemyCatalog.load(path)
    except EnemyCatalogError as exc:
        logger.debug(f"固定名册未启用（回落旧动态路径）：{exc}")
        return None
    except OSError:
        return None
    return catalog
