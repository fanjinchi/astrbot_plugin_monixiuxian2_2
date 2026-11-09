# managers/enemy_catalog.py
"""Fixed enemy-roster runtime: immutable catalog, segment resolver, one mapper.

Trellis 10-10-pve-enemy-catalog-runtime (Child B) deliverable: the 28 roster
enemies and 4 world bosses get their combat profiles rendered from the
design_docs roster CSVs into ``config/enemies.json`` (schema_version=2) by
``scripts/sync_content_to_config.py``; this module loads, validates, indexes
and maps them to ``FighterState`` through the single mapper below. Roster
numbers are absolute per-segment design panels — no exp_needed derivation, no
random level, no category multipliers, no ±10% jitter (R2/AC2); the
``pve.difficulty_multiplier`` knob multiplies damage only, at one place in
``spawn_enemy``.

Child B wires no callers: this module never writes the DB, grants rewards or
touches adventure/rift lifecycles (Batch 5 cutover, Child C/D own those).
World bosses are immutable profiles / copy-to-snapshot inputs only;
instance lifecycle and dissipation belong to Child D.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from astrbot.api import logger
except ImportError:  # 独立测试环境无 astrbot
    import logging

    logger = logging.getLogger("enemy_catalog")

try:
    from ..core.enemy_schema import validate_enemy_document
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
    """Fail-closed error: the fixed roster document is rejected."""


@dataclass(frozen=True)
class EnemyCombatProfile:
    """Immutable combat profile of one roster enemy (PROFILE_VERSION=1 shape).

    Attributes:
        id: stable roster id (enemies.csv ``id`` column).
        name: full display name (elites carry the affix prefix, baked in CSV).
        segment: realm segment label (练气/筑基/金丹/元婴).
        category: tier ("normal" / "elite" / "boss").
        archetype: archetype tag (均衡/坚壳/猛击/迅捷; provenance display only).
        level_index: designed level (1-based; fed into FighterState.level_index).
        level_range: inclusive served level band (low, high), 1-based.
        hp: absolute health panel value.
        damage: absolute damage panel value.
        agility: absolute agility panel value.
        speed: absolute speed panel value.
        armor_value: absolute armor panel value.
        crit_rate: raw percent value (0 means "use the engine base crit rate").
        affix: elite affix name, else empty string.
        boss_skill: boss mechanic name, else empty string.
        trigger_skills: materialized trigger-skill dicts (sync output).
        ultimates: materialized ultimate dicts.
        exp: reward placeholder (always 0 until Step 7 economy takes over).
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
    """Immutable combat + metadata profile of one world boss.

    Child D consumes it as snapshot input only; nothing here instantiates or
    schedules instances.

    Attributes:
        id / name / segment / level_index / hp / damage / agility / speed /
        armor_value / crit_rate: same semantics as :class:`EnemyCombatProfile`.
        signature_skill: signature-skill display name (world_bosses.csv).
        skill_key: signature-skill mechanic key (连咬/反震/灼烧/绞杀).
        trigger_skills / ultimates: materialized skill dict tuples.
        phase_thresholds: (P2, P3) remaining-HP thresholds, descending.
        phase2_damage_multiplier: P2 damage multiplier.
        phase3_damage_multiplier: P3 damage multiplier.
        phase3_armor_multiplier: P3 armor multiplier.
        lifetime_h / daily_attempts / respawn_after_kill_h /
        respawn_after_dissipate_h: spawn/dissipation metadata (hours/attempts).
        profile_version: generated profile contract version (persisted into
            instance/ledger facts; previously dropped by from_dict).
        spawn_text / phase2_text / phase3_text / kill_text / dissipate_text:
            the five narrative copy strings rendered for spawn/phase2/phase3/
            defeated/dissipated events (prd R7, no code fallback).
        narrative_approved: narrative gate; False forbids any broadcast even
            when the copy strings are present.
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
    profile_version: int
    spawn_text: str
    phase2_text: str
    phase3_text: str
    kill_text: str
    dissipate_text: str
    narrative_approved: bool

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
            profile_version=int(entry.get("profile_version", 0)),
            spawn_text=entry["spawn_text"],
            phase2_text=entry["phase2_text"],
            phase3_text=entry["phase3_text"],
            kill_text=entry["kill_text"],
            dissipate_text=entry["dissipate_text"],
            narrative_approved=bool(entry["narrative_approved"]),
        )


def profile_to_enemy(
    profile: EnemyCombatProfile | WorldBossProfile,
    difficulty_multiplier: float = 1.0,
    user_id_prefix: str = "enemy",
    seq: int = 0,
    token: int = 0,
) -> Enemy:
    """Instantiate one immutable combat profile into a battle-carrier ``Enemy``.

    Absolute panel values are copied verbatim; ``difficulty_multiplier``
    multiplies **damage only** (R2; same int-truncation convention as the old
    ``spawn_enemy``). Skill tuples are copied dict-by-dict into lists so the
    immutable catalog profile can never be dirtied by battle-side writes.

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
    """The single Enemy → FighterState mapper (roster/dynamic/group shared, R3).

    Field-for-field aligned with the acceptance-gate
    design_docs/content-design/sim_pve_acceptance.py ``build_monster``:

    - beast unarmed: ``weapon_k=0.5``, ``base_damage=5`` (附录 C.4; numerically
      identical to the engine's fallback, written explicitly for field-level
      equality).
    - ``block_armor_value`` equals innate armor, fully counted in block
      (design D2).
    - ``level_index`` passes through (pit #5 fixed: armor mitigation
      K=100+10×defender level no longer stuck at 1); carriers without it
      (old Enemy instances, 0) keep the engine default 1 — point-compatible.
    - ``crit_rate`` > 0 overrides the engine base crit as percent/100 (Step 3
      decision, pit #3); 0/absent keeps the default.
    - trigger_skills/ultimates pass through verbatim (pit fixed: boss
      mechanics previously never reached the battle).

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
    """Immutable fixed-roster catalog: (segment, category) index + resolver.

    Construction validates the whole document
    (:func:`core.enemy_schema.validate_enemy_document`); any contract error
    fails closed with :class:`EnemyCatalogError` — the runtime can never
    consume a half-old/half-new mixed format.

    Attributes:
        meta: document audit header (schema/profile versions, source CSV
            hashes etc.).
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
            path: config/enemies.json (or a test tmp preview) path.

        Returns:
            Ready immutable catalog.

        Raises:
            EnemyCatalogError: file unreadable or contract-invalid (v1
                legacy files included — they must be re-rendered by sync,
                Batch 5 cutover).
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
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except ValueError as exc:
            # json.JSONDecodeError / UnicodeDecodeError: keep the documented
            # EnemyCatalogError contract so load_catalog can degrade instead of
            # crashing plugin startup.
            raise EnemyCatalogError(f"敌人名册配置不是合法 JSON：{exc}") from exc
        if not isinstance(doc, dict):
            raise EnemyCatalogError("敌人名册配置必须是 JSON 对象")
        return doc

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

        Levels outside all bands clamp to the first/last band, matching the
        old dynamic path's "fall back to the highest range group" semantics.

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

        Same name/signature as the old ``EnemyManager.spawn_enemy`` to keep
        the Batch 5 cutover mechanical; the difference is this child's reason
        to exist: panels are the designed segment's absolute values — no
        random level, no category multipliers, no ±10% jitter — and the
        difficulty multiplier hits damage only (R2/AC5).

        Args:
            player_level: player level, selects the serving segment.
            category: "normal" / "elite" / "boss".
            difficulty_multiplier: game_config ``pve.difficulty_multiplier``.
            rng: injectable randomness source (tests freeze seeds).

        Returns:
            Enemy carrier ready for :func:`build_enemy_fighter`.

        Raises:
            EnemyCatalogError: the (segment, category) bucket is absent.
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


def load_catalog(path: Path) -> EnemyCatalog | None:
    """Best-effort catalog loader for future call-site wiring.

    Args:
        path: enemies config path.

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
