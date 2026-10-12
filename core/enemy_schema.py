# core/enemy_schema.py
"""Enemy/world-boss content schema: shared contract between sync adapter and runtime.

Single source of truth for the fixed-roster PVE pipeline
(Trellis 10-10-pve-enemy-catalog-runtime, design_docs pve-enemy-design.md Step
0-6 封板数值). Pure stdlib on purpose: imported both by the runtime
(``managers/enemy_catalog.py``) and by the offline sync adapter
(``scripts/sync_content_to_config.py``) which must not pull astrbot deps.

Contract versions (R1/AC2):

- ``SCHEMA_VERSION``: version of the *generated config document* shape.
- ``PROFILE_VERSION``: version of a single enemy/world-boss combat profile.
  Bump PROFILE_VERSION whenever the profile field set changes.

Governance mirrors the design: formal enemy content may only be written by the
adapter when every source row is ``status=final`` AND an explicit approval
manifest covers the dataset hash/column range/narrative decision; otherwise
rendering is preview-only. 战斗列与叙事列独立获批：叙事占位不随整表状态放行。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 2
PROFILE_VERSION = 1

GENERATOR = "scripts/sync_content_to_config.py"

# ---------------------------------------------------------------- roster CSV

ROSTER_CSV = "enemies.csv"
WORLD_BOSS_CSV = "world_bosses.csv"

#: Numeric columns every syncable roster row (tier normal/elite/boss) must set.
ROSTER_PANEL_COLUMNS = (
    "level",
    "hp",
    "damage",
    "agility",
    "speed",
    "armor_value",
)
#: Tier values the fixed roster accepts. Guardian rows are specialist config,
#: never compiled into roster entries (R4: groups keep their own source).
ROSTER_TIERS = ("normal", "elite", "boss")
GUARDIAN_TIER = "guardian"

VALID_AFFIXES = ("狂暴", "坚甲", "嗜血")
VALID_BOSS_SKILLS = ("拱土疗伤", "狼王连咬", "鳞甲反震", "九尾现形")

# ------------------------------------------------------------------ WB CSV

WB_PANEL_COLUMNS = ("level", "hp", "damage", "agility", "speed", "armor_value")
WB_NUMERIC_META_COLUMNS = (
    "phase2_dmg_mult",
    "phase3_dmg_mult",
    "phase3_armor_mult",
    "lifetime_h",
    "daily_attempts",
    "respawn_kill_h",
    "respawn_dissipate_h",
)
#: 世界 Boss 纪律（附录 F 用户拍板）：禁用一切净效果为「回复/减免 Boss 血量」
#: 的机制（回血/吸血/减伤/免死）。护甲 buff 亦属"减免血量"通道，一并禁用。
WORLD_BOSS_FORBIDDEN_EFFECTS = ("heal", "damage_reduction", "survive", "buff")
#: 允许的阶段阈值格式 "hi/lo"（P2/P3 触发 HP 占比，百分数）。
PHASE_COUNT = 2

# ------------------------------------------- mechanic materialization maps
# 权威口径 = pve-enemy-design.md 附录 D.2/D.3 + F（Q3c/Step6 定案数值）。
# 必须与设计验收门 design_docs/content-design/sim_pve_acceptance.py 的
# AFFIX_SKILLS/BOSS_MECHANICS 逐字段一致（tests/test_enemy_catalog_runtime.py
# TestSimParity 对照断言），否则运行时与验收模拟分叉。
# 狂暴/坚甲是纯面板词缀（CSV 绝对值已烘焙），不挂触发技；只有嗜血是机制。

AFFIX_TRIGGER_SKILLS: dict[str, list[dict[str, Any]]] = {
    "嗜血": [
        {
            "name": "嗜血",
            "trigger_timing": "on_attack",
            "trigger_rate": 0.20,
            "effect_type": "heal",
            "effect_value": 0.20,
            "vampire": True,
        }
    ],
}

BOSS_SKILL_MECHANICS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "拱土疗伤": {
        "trigger_skills": [
            {
                "name": "拱土疗伤",
                "trigger_timing": "on_defense",
                "trigger_rate": 0.12,
                "effect_type": "heal",
                "heal_percent": 0.07,
            }
        ],
        "ultimates": [],
    },
    "狼王连咬": {
        "trigger_skills": [
            {
                "name": "狼王连咬",
                "trigger_timing": "on_attack",
                "trigger_rate": 0.15,
                "effect_type": "combo",
                "effect_value": 0.5,
            }
        ],
        "ultimates": [],
    },
    "鳞甲反震": {
        "trigger_skills": [
            {
                "name": "鳞甲反震",
                "trigger_timing": "on_defense",
                "trigger_rate": 0.20,
                "effect_type": "counter",
                "effect_value": 0.3,
            }
        ],
        "ultimates": [],
    },
    "九尾现形": {
        "trigger_skills": [],
        "ultimates": [
            {
                "id": "boss_rage",
                "name": "九尾现形",
                "trigger_self_hp_below": 0.30,
                "trigger_rate": 1.0,
                "effect_type": "buff",
                "stat": "damage",
                "effect_value": 0.10,
                "duration": 3,
            }
        ],
    },
}

# --------------------------------- world boss signature skill (附录 F 定案)
# key = world_bosses.csv ``skill_key`` 列；参数出处见 F 节（连咬/反震 = Q3c
# 定案；灼烧 = dot 20%/15%×3 回合照 skills.csv 已验证行；绞杀 = stun 15%）。

WORLD_BOSS_SIGNATURE_SKILLS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "连咬": {
        "trigger_skills": [
            {
                "name": "连咬",
                "trigger_timing": "on_attack",
                "trigger_rate": 0.15,
                "effect_type": "combo",
                "effect_value": 0.5,
            }
        ],
    },
    "反震": {
        "trigger_skills": [
            {
                "name": "反震",
                "trigger_timing": "on_defense",
                "trigger_rate": 0.20,
                "effect_type": "counter",
                "effect_value": 0.3,
            }
        ],
    },
    "灼烧": {
        "trigger_skills": [
            {
                "name": "灼烧",
                "trigger_timing": "on_attack",
                "trigger_rate": 0.20,
                "effect_type": "dot",
                "effect_value": 0.15,
                "duration": 3,
            }
        ],
    },
    "绞杀": {
        "trigger_skills": [
            {
                "name": "绞杀",
                "trigger_timing": "on_attack",
                "trigger_rate": 0.15,
                "effect_type": "stun",
            }
        ],
    },
}

# ------------------------------------------------------------------ helpers


VALID_SEGMENTS = ("练气", "筑基", "金丹", "元婴")


def sha256_file(path) -> str:
    """Return the hex SHA-256 digest of a file's raw bytes.

    Args:
        path: Path (or path-like) to hash.

    Returns:
        64-char lowercase hex digest.
    """
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def parse_level_range(text: str) -> tuple[int, int] | None:
    """Parse a ``level_range`` CSV cell like ``1-9`` into an inclusive pair.

    Args:
        text: Raw cell value.

    Returns:
        ``(low, high)`` or None when malformed/empty.
    """
    text = (text or "").strip()
    if "-" not in text:
        return None
    lo, _, hi = text.partition("-")
    try:
        lo_i, hi_i = int(lo), int(hi)
    except ValueError:
        return None
    if lo_i < 1 or lo_i > hi_i:
        # 1-based 闭区间：0-based 旧 residue（坑 #4）在闸门直接拒绝
        return None
    return lo_i, hi_i


def parse_phase_thresholds(text: str) -> tuple[float, float] | None:
    """Parse ``phase_thresholds`` like ``60/20`` into fractions.

    Args:
        text: Raw cell value.

    Returns:
        ``(p2, p3)`` HP-fraction thresholds (descending) or None if invalid.
    """
    parts = (text or "").strip().split("/")
    if len(parts) != PHASE_COUNT:
        return None
    try:
        vals = [int(p) for p in parts]
    except ValueError:
        return None
    if not all(0 < v < 100 for v in vals) or vals[0] <= vals[1]:
        return None
    return tuple(v / 100.0 for v in vals)


def _to_int(value: Any, ctx: str, col: str, errors: list[str]) -> int:
    """Parse a CSV cell as int, appending an error on failure.

    Args:
        value: Raw CSV cell.
        ctx: Row context label used in the error message.
        col: Column name used in the error message.
        errors: Shared error sink; appended on parse failure.

    Returns:
        Parsed int, or -1 sentinel when invalid (error recorded).
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        errors.append(f"{ctx}: column {col!r} must be an integer, got {value!r}")
        return -1


def _to_float(value: Any, ctx: str, col: str, errors: list[str]) -> float:
    """Parse a CSV cell as float, appending an error on failure.

    Args:
        value: Raw CSV cell.
        ctx: Row context label used in the error message.
        col: Column name used in the error message.
        errors: Shared error sink; appended on parse failure.

    Returns:
        Parsed float, or NaN when invalid (error recorded).
    """
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        errors.append(f"{ctx}: column {col!r} must be numeric, got {value!r}")
        return float("nan")


# ------------------------------------------------------------ profile build


def build_enemy_profile(row: dict, ctx: str, errors: list[str]) -> dict | None:
    """Build one roster combat profile from an enemies.csv row.

    Guardian-tier rows return None (without errors): they are specialist
    group config validated by the group path, not fixed-roster entries.

    Args:
        row: CSV row dict.
        ctx: Human-readable location for error messages.
        errors: Error sink list, appended in place.

    Returns:
        Generated config entry, or None on error / guardian tier.
    """
    tier = (row.get("tier") or "").strip()
    if tier == GUARDIAN_TIER:
        return None
    if tier not in ROSTER_TIERS:
        errors.append(f"{ctx}: unknown tier {tier!r} (allowed: {ROSTER_TIERS})")
        return None

    entry_id = (row.get("id") or "").strip()
    name = (row.get("name") or "").strip()
    segment = (row.get("segment") or "").strip()
    before = len(errors)
    if not entry_id:
        errors.append(f"{ctx}: id is required")
        return None
    if not name:
        errors.append(f"{ctx}: name is required")
    if segment not in VALID_SEGMENTS:
        errors.append(f"{ctx}: invalid segment {segment!r}")

    panel: dict[str, int] = {}
    for col in ROSTER_PANEL_COLUMNS:
        panel[col] = _to_int(row.get(col), ctx, col, errors)
    for col in ("hp", "damage", "agility", "speed"):
        if panel.get(col, 0) < 1:
            errors.append(f"{ctx}: column {col!r} must be >= 1")
    if panel.get("armor_value", 0) < 0:
        errors.append(f"{ctx}: armor_value must be >= 0")

    lr = parse_level_range(row.get("level_range", ""))
    if lr is None:
        errors.append(f"{ctx}: bad level_range {row.get('level_range')!r}")
        return None
    level = panel.get("level", 0)
    if not (lr[0] <= level <= lr[1]):
        errors.append(f"{ctx}: level {level} outside level_range {lr}")

    affix = (row.get("affix") or "").strip()
    boss_skill = (row.get("boss_skill") or "").strip()
    trigger_skills: list[dict] = []
    ultimates: list[dict] = []
    if tier == "normal":
        if affix or boss_skill:
            errors.append(f"{ctx}: normal tier must not declare affix/boss_skill")
    elif tier == "elite":
        if affix not in VALID_AFFIXES:
            errors.append(f"{ctx}: elite affix {affix!r} not in {VALID_AFFIXES}")
            return None
        if boss_skill:
            errors.append(f"{ctx}: elite must not declare boss_skill")
        trigger_skills = [dict(s) for s in AFFIX_TRIGGER_SKILLS.get(affix, [])]
    elif tier == "boss":
        if boss_skill not in VALID_BOSS_SKILLS:
            errors.append(
                f"{ctx}: boss_skill {boss_skill!r} not in {VALID_BOSS_SKILLS}"
            )
            return None
        if affix:
            errors.append(f"{ctx}: boss tier must not declare affix")
        mech = BOSS_SKILL_MECHANICS[boss_skill]
        trigger_skills = [dict(s) for s in mech["trigger_skills"]]
        ultimates = [dict(u) for u in mech["ultimates"]]

    if len(errors) > before:
        return None
    return {
        "id": entry_id,
        "profile_version": PROFILE_VERSION,
        "name": name,
        "segment": segment,
        "category": tier,
        "archetype": (row.get("archetype") or "").strip(),
        "level_index": panel["level"],
        "level_range": [lr[0], lr[1]],
        "hp": panel["hp"],
        "damage": panel["damage"],
        "agility": panel["agility"],
        "speed": panel["speed"],
        "armor_value": panel["armor_value"],
        # 名册 CSV 无暴击列：0 = 引擎默认基础暴击率（Step3 接线语义）
        "crit_rate": 0,
        "affix": affix,
        "boss_skill": boss_skill,
        "trigger_skills": trigger_skills,
        "ultimates": ultimates,
        "exp": 0,
        "status": (row.get("status") or "").strip(),
        "narrative_status": (row.get("narrative_status") or "").strip(),
    }


def build_world_boss_profile(row: dict, ctx: str, errors: list[str]) -> dict | None:
    """Build one immutable world-boss combat profile from a world_bosses.csv row.

    Child B ships profile data only — spawn/lifecycle/cleanup belongs to
    Child D; this function never touches instances or the DB.

    Args:
        row: CSV row dict.
        ctx: Error location prefix.
        errors: Error sink list.

    Returns:
        Generated config entry, or None on error.
    """
    entry_id = (row.get("id") or "").strip()
    if not entry_id:
        errors.append(f"{ctx}: id is required")
        return None

    before = len(errors)
    wb_name = (row.get("name") or "").strip()
    wb_segment = (row.get("segment") or "").strip()
    if not wb_name:
        errors.append(f"{ctx}: name is required")
    if wb_segment not in VALID_SEGMENTS:
        errors.append(f"{ctx}: invalid segment {wb_segment!r}")
    panel: dict[str, int] = {}
    for col in WB_PANEL_COLUMNS:
        panel[col] = _to_int(row.get(col), ctx, col, errors)
    for col in ("hp", "damage", "agility", "speed"):
        if panel.get(col, 0) < 1:
            errors.append(f"{ctx}: column {col!r} must be >= 1")
    if panel.get("armor_value", 0) < 0:
        errors.append(f"{ctx}: armor_value must be >= 0")

    meta: dict[str, float] = {}
    for col in WB_NUMERIC_META_COLUMNS:
        meta[col] = _to_float(row.get(col), ctx, col, errors)
    for col in (
        "lifetime_h",
        "daily_attempts",
        "respawn_kill_h",
        "respawn_dissipate_h",
    ):
        v = meta.get(col, 0)
        if v <= 0 or v != int(v):
            errors.append(
                f"{ctx}: {col} must be a positive integer, got {row.get(col)!r}"
            )
        else:
            meta[col] = int(v)
    for col in ("phase2_dmg_mult", "phase3_dmg_mult", "phase3_armor_mult"):
        if meta.get(col, 0) != meta.get(col) or meta.get(col, 0) <= 0:
            errors.append(f"{ctx}: {col} must be > 0")

    phases = parse_phase_thresholds(row.get("phase_thresholds", ""))
    if phases is None:
        errors.append(
            f"{ctx}: phase_thresholds must be two descending percents "
            f"like '60/20', got {row.get('phase_thresholds')!r}"
        )
        return None

    skill_key = (row.get("skill_key") or "").strip()
    if skill_key not in WORLD_BOSS_SIGNATURE_SKILLS:
        errors.append(
            f"{ctx}: skill_key {skill_key!r} not in "
            f"{tuple(WORLD_BOSS_SIGNATURE_SKILLS)}"
        )
        return None
    trigger_skills = [
        dict(s) for s in WORLD_BOSS_SIGNATURE_SKILLS[skill_key]["trigger_skills"]
    ]
    # 附录 F 纪律：招牌技变更必须重测锚值；禁净回复/减免类效果入世界 Boss。
    for skill in trigger_skills:
        if skill.get("effect_type") in WORLD_BOSS_FORBIDDEN_EFFECTS:
            errors.append(
                f"{ctx}: world-boss signature effect_type "
                f"{skill.get('effect_type')!r} is forbidden by the "
                "no-heal/no-reduce discipline (pve-enemy-design.md 附录 F)"
            )

    if len(errors) > before:
        return None
    return {
        "id": entry_id,
        "profile_version": PROFILE_VERSION,
        "name": wb_name,
        "segment": wb_segment,
        "level_index": panel["level"],
        "hp": panel["hp"],
        "damage": panel["damage"],
        "agility": panel["agility"],
        "speed": panel["speed"],
        "armor_value": panel["armor_value"],
        "crit_rate": 0,
        "signature_skill": (row.get("signature_skill") or "").strip(),
        "skill_key": skill_key,
        "trigger_skills": trigger_skills,
        "ultimates": [],
        "phase_thresholds": [phases[0], phases[1]],
        "phase2_damage_multiplier": meta["phase2_dmg_mult"],
        "phase3_damage_multiplier": meta["phase3_dmg_mult"],
        "phase3_armor_multiplier": meta["phase3_armor_mult"],
        "lifetime_h": int(meta["lifetime_h"]),
        "daily_attempts": int(meta["daily_attempts"]),
        "respawn_after_kill_h": int(meta["respawn_kill_h"]),
        "respawn_after_dissipate_h": int(meta["respawn_dissipate_h"]),
        "status": (row.get("status") or "").strip(),
        "narrative_status": (row.get("narrative_status") or "").strip(),
    }


# ------------------------------------------------------------ doc validation

_ENEMY_PROFILE_REQUIRED_KEYS = {
    "id",
    "profile_version",
    "name",
    "segment",
    "category",
    "level_index",
    "level_range",
    "hp",
    "damage",
    "agility",
    "speed",
    "armor_value",
    "crit_rate",
    "affix",
    "boss_skill",
    "trigger_skills",
    "ultimates",
    "status",
    "narrative_status",
}

_WB_PROFILE_REQUIRED_KEYS = {
    "id",
    "profile_version",
    "name",
    "segment",
    "level_index",
    "hp",
    "damage",
    "agility",
    "speed",
    "armor_value",
    "crit_rate",
    "signature_skill",
    "skill_key",
    "trigger_skills",
    "phase_thresholds",
    "phase2_damage_multiplier",
    "phase3_damage_multiplier",
    "phase3_armor_multiplier",
    "lifetime_h",
    "daily_attempts",
    "respawn_after_kill_h",
    "respawn_after_dissipate_h",
    "status",
    "narrative_status",
}

_LEGACY_KEYS = {
    "difficulty_coefficients",
    "templates",
    "category_multipliers",
    "level_range",  # top-level only; profiles carry their own
    "jitter",
}


def _check_trigger_skill(skill: dict, ctx: str, errors: list[str]) -> None:
    """Validate one trigger-skill dict shape, appending errors.

    Only the structural minimum is checked (object with timing/effect/rate
    keys); all skill values come from the code-materialized mechanic maps
    (AFFIX_TRIGGER_SKILLS / BOSS_SKILL_MECHANICS / signature skills) and
    have no CSV injection channel.

    Args:
        skill: Candidate trigger skill dict.
        ctx: Row context label used in error messages.
        errors: Shared error sink.
    """
    if not isinstance(skill, dict):
        errors.append(f"{ctx}: trigger skill must be an object")
        return
    missing = {"trigger_timing", "effect_type", "trigger_rate"} - set(skill)
    if missing:
        errors.append(f"{ctx}: trigger skill missing keys {sorted(missing)}")


def validate_enemy_document(doc: dict, expected_count: int | None = None) -> list[str]:
    """Validate a generated ``config/enemies.json`` roster document.

    Fail-closed: unknown schema versions, missing sections, duplicate ids and
    legacy dynamic-spawn keys are all rejected so the fixed-roster runtime can
    never consume an old/mixed format (design §2, R2).

    Args:
        doc: Parsed config JSON.
        expected_count: Optional roster size assertion (28 + 4).

    Returns:
        List of error strings; empty means valid.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["enemy config must be a JSON object"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version {doc.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}（旧动态敌人配置需经 sync 重新生成）"
        )
    for key in _LEGACY_KEYS:
        if key in doc:
            errors.append(f"legacy key {key!r} must not exist in v{SCHEMA_VERSION} doc")
    enemies = doc.get("enemies")
    bosses = doc.get("world_bosses")
    if not isinstance(enemies, list) or not enemies:
        errors.append("enemies: missing or empty list")
        return errors
    if not isinstance(bosses, list) or not bosses:
        errors.append("world_bosses: missing or empty list")
        return errors
    if expected_count is not None and len(enemies) + len(bosses) != expected_count:
        errors.append(
            f"roster size {len(enemies)}+{len(bosses)} != expected {expected_count}"
        )
    seen: set[str] = set()
    for i, e in enumerate(enemies):
        ctx = f"enemies[{i}]"
        missing = _ENEMY_PROFILE_REQUIRED_KEYS - set(e)
        if missing:
            errors.append(f"{ctx}: missing keys {sorted(missing)}")
            continue
        if e["id"] in seen:
            errors.append(f"{ctx}: duplicate id {e['id']!r}")
        seen.add(e["id"])
        if e["profile_version"] != PROFILE_VERSION:
            errors.append(
                f"{ctx}: unsupported profile_version {e['profile_version']!r}"
            )
        if e["category"] not in ROSTER_TIERS:
            errors.append(f"{ctx}: bad category {e['category']!r}")
        if e["hp"] < 1 or e["damage"] < 1 or e["agility"] < 1 or e["speed"] < 1:
            errors.append(f"{ctx}: panel values must be >= 1")
        if e["armor_value"] < 0 or e["level_index"] < 1:
            errors.append(f"{ctx}: armor/level_index out of range")
        for j, sk in enumerate(e["trigger_skills"]):
            _check_trigger_skill(sk, f"{ctx}.trigger_skills[{j}]", errors)
    seen_wb: set[str] = set()
    for i, b in enumerate(bosses):
        ctx = f"world_bosses[{i}]"
        missing = _WB_PROFILE_REQUIRED_KEYS - set(b)
        if missing:
            errors.append(f"{ctx}: missing keys {sorted(missing)}")
            continue
        if b["id"] in seen_wb:
            errors.append(f"{ctx}: duplicate id {b['id']!r}")
        seen_wb.add(b["id"])
        if b["profile_version"] != PROFILE_VERSION:
            errors.append(f"{ctx}: unsupported profile_version")
        if b["skill_key"] not in WORLD_BOSS_SIGNATURE_SKILLS:
            errors.append(f"{ctx}: unknown skill_key {b['skill_key']!r}")
        th = b["phase_thresholds"]
        if (
            not isinstance(th, list)
            or len(th) != PHASE_COUNT
            or not (th[0] > th[1] > 0)
        ):
            errors.append(f"{ctx}: phase_thresholds must be two descending fractions")
        for j, sk in enumerate(b["trigger_skills"]):
            _check_trigger_skill(sk, f"{ctx}.trigger_skills[{j}]", errors)
            if isinstance(sk, dict) and sk.get("effect_type") in (
                WORLD_BOSS_FORBIDDEN_EFFECTS
            ):
                errors.append(
                    f"{ctx}.trigger_skills[{j}]: forbidden effect_type "
                    f"{sk.get('effect_type')!r} on world boss"
                )
    return errors


# ---------------------------------------------------------------- approval


def load_manifest(path) -> dict:
    """Read the approval manifest JSON from a path."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_approval(
    manifest: dict | None,
    csv_hashes: dict[str, str],
    rows_by_dataset: dict[str, list[dict]],
    *,
    require_final: bool,
) -> list[str]:
    """Fail-closed gate for the formal write path (R1/AC1).

    Args:
        manifest: Parsed approval manifest or None.
        csv_hashes: {dataset filename: sha256 hex} of the actual CSV sources.
        rows_by_dataset: {filename: active rows} rendered from the same CSVs.
        require_final: Formal mode requires every row ``status=final``.

    Returns:
        Error strings; empty list means the write may proceed.
    """
    errors: list[str] = []
    if manifest is None:
        return ["缺少 --approval-manifest：敌人正式写路径拒绝执行（fail closed）"]
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict):
        return ["manifest 缺少 datasets 映射"]
    if set(datasets) != set(csv_hashes):
        errors.append(
            f"manifest 数据集范围不匹配: manifest={sorted(datasets)} "
            f"actual={sorted(csv_hashes)}"
        )
    for name, digest in sorted(csv_hashes.items()):
        spec = datasets.get(name)
        if not isinstance(spec, dict):
            errors.append(f"{name}: manifest 缺少该数据集条目")
            continue
        declared = spec.get("sha256")
        if declared != digest:
            errors.append(
                f"{name}: CSV SHA-256 漂移 manifest={declared!r} actual={digest!r}"
            )
        columns = spec.get("columns")
        if not isinstance(columns, list) or not columns:
            errors.append(f"{name}: manifest columns 缺失或为空")
            continue
        approved = set(columns)
        rows = rows_by_dataset.get(name) or []
        header = set().union(*(set(r) for r in rows)) if rows else set()
        extra = header - approved
        if extra:
            errors.append(f"{name}: 列越权 {sorted(extra)}（manifest 未批准）")
    if require_final:
        for name, rows in sorted(rows_by_dataset.items()):
            spec = datasets.get(name) or {}
            # 叙事决策由 manifest 显式列出获批值；缺省只放行 定稿/豁免。
            approved_narr = spec.get("narrative_status") or ["定稿", "豁免"]
            approved_narr = set(approved_narr)
            for row in rows:
                rid = (row.get("id") or "?").strip()
                if (row.get("status") or "").strip() != "final":
                    errors.append(
                        f"{name}/{rid}: status 非 final（draft 内容只能 preview 渲染）"
                    )
                if (row.get("narrative_status") or "").strip() not in approved_narr:
                    errors.append(
                        f"{name}/{rid}: narrative_status "
                        f"{(row.get('narrative_status') or '').strip()!r} 未在 manifest "
                        "叙事决策中获批"
                    )
    return errors
