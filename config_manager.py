import json
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .data.default_configs import (
    ALCHEMY_CONFIG,
    BOSS_CONFIG,
    DEFAULT_NARRATIVE_CONFIG,
    IMPART_CONFIG,
    NARRATIVE_SCENE_VARS,
    RIFT_CONFIG,
    SECT_CONFIG,
    SECT_FACTIONS,
    SECT_TASKS,
)

# 叙事文案辅助函数单源在 utils/narrative_text.py（可独立加载，供 managers 的
# try/except 测试加载分支使用）；渲染入口 render_narrative 等由调用方直接从该
# 模块引入，此处仅引入校验逻辑所需符号。
from .utils.narrative_text import (
    _NARRATIVE_ROUTES,
    NARRATIVE_BUCKET_KEYS,
    _iter_scene_entries,
    extract_template_vars,
)

_CHINESE_DIGITS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _stage_to_chinese(stage: int) -> str:
    """Convert a 1-based stage number to its Chinese digit name.

    Args:
        stage: Stage number, typically 1-9 for normal levels.

    Returns:
        Chinese digit string (e.g. 1 -> "一"), or the numeric string if out of range.
    """
    if 1 <= stage <= 9:
        return _CHINESE_DIGITS[stage - 1]
    return str(stage)


class ConfigManager:
    """配置管理器，加载境界、物品、武器和丹药配置"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._level_config: dict = {}  # 灵修新结构配置
        self._body_level_config: dict = {}  # 体修新结构配置
        self.level_data: list[dict] = []  # 灵修境界数据（运行时合成，兼容 shim）
        self.body_level_data: list[dict] = []  # 体修境界数据（运行时合成，兼容 shim）
        self.items_data: dict[str, dict] = {}  # 物品数据，key为物品名称
        self.weapons_data: dict[str, dict] = {}  # 武器数据，key为武器名称
        self.pills_data: dict[str, dict] = {}  # 破境丹数据，key为丹药名称
        self.exp_pills_data: dict[str, dict] = {}  # 修为丹数据，key为丹药名称
        self.utility_pills_data: dict[str, dict] = {}  # 功能丹数据，key为丹药名称
        self.storage_rings_data: dict[str, dict] = {}  # 储物戒数据，key为储物戒名称

        # 新增系统配置
        self.sect_config: dict[str, Any] = {}
        self.boss_config: dict[str, Any] = {}
        self.rift_config: dict[str, Any] = {}
        self.alchemy_config: dict[str, Any] = {}
        self.sect_factions: dict[str, Any] = {}  # 默认宗门定义
        self.sect_tasks: dict[str, Any] = {}  # 宗门建设/师承任务池

        # Load new system configs
        self.skills_data: dict[str, dict] = {}  # Skill definitions
        self.heart_methods_data: dict[str, dict] = {}  # Heart method definitions
        self.impart_config: dict[str, Any] = {}  # Impart tier rewards
        self.narrative_config: dict[str, Any] = {}  # 叙事文案模板与变体池
        self.spirit_root_descriptions: dict[
            str, dict
        ] = {}  # 灵根/体质评价，key为灵根名

        self._load_all()

    def get_level_data(self, cultivation_type: str = "灵修") -> list[dict]:
        """根据修炼类型获取对应的境界数据"""
        if cultivation_type == "体修":
            return self.body_level_data
        return self.level_data

    def _get_level_config(self, cultivation_type: str = "灵修") -> dict:
        """Return the raw level configuration dict for the given route."""
        if cultivation_type == "体修":
            return self._body_level_config
        return self._level_config

    @staticmethod
    def _derive_max_level(realms: list[str]) -> int:
        """Derive the highest level from the realm list.

        Each realm has 9 normal levels plus one "initial" level, so max level is
        ``len(realms) * 10 - 1``.
        """
        return max(0, len(realms) * 10 - 1)

    def get_max_level(self, cultivation_type: str = "灵修") -> int:
        """Return the highest valid level index for the given route."""
        config = self._get_level_config(cultivation_type)
        return self._derive_max_level(config.get("realms", []))

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        """Calculate the display name for a 1-based level index.

        Normal levels are named ``{realm}{stage}阶`` (e.g. 练气一阶). Every 10th
        level is named ``{next realm}初期`` to keep the existing convention.
        Out-of-range levels fall back to ``境界{level_index}``.

        Args:
            level_index: 1-based level number.
            cultivation_type: "灵修" or "体修".

        Returns:
            The Chinese level name.
        """
        if level_index < 1:
            return f"境界{level_index}"

        config = self._get_level_config(cultivation_type)
        realms = config.get("realms", [])
        if not realms:
            return f"境界{level_index}"

        max_level = self._derive_max_level(realms)
        if level_index > max_level:
            return f"境界{level_index}"

        realm_index = (level_index - 1) // 10
        stage = (level_index - 1) % 10 + 1

        if stage == 10:
            if realm_index + 1 < len(realms):
                return f"{realms[realm_index + 1]}初期"
            return f"境界{level_index}"

        return f"{realms[realm_index]}{_stage_to_chinese(stage)}阶"

    def get_exp_needed(self, level_index: int, cultivation_type: str = "灵修") -> int:
        """Calculate the EXP required to break through from ``level_index``.

        Uses the three-segment formula from the design document:
        - ``E(L) = early_a * L^early_exp`` for ``L <= 10``
        - ``E(L) = pivot10 * (L / 10)`` for ``10 < L <= mid_end_level``
        - ``E(L) = pivot50 * (L / mid_end_level)^late_exp`` for ``L > mid_end_level``

        Args:
            level_index: 1-based current level.
            cultivation_type: "灵修" or "体修" (uses the same formula parameters).

        Returns:
            Integer EXP needed for the next level; 0 if the level is invalid.
        """
        if level_index < 1:
            return 0

        config = self._get_level_config(cultivation_type)
        curve = config.get("exp_curve", {})
        early_a = curve.get("early_a", 1800)
        early_exp = curve.get("early_exp", 1.5)
        mid_end_level = curve.get("mid_end_level", 50)
        late_exp = curve.get("late_exp", 1.7)

        if level_index <= 10:
            return int(early_a * (level_index**early_exp))

        pivot10 = int(early_a * (10**early_exp))
        if level_index <= mid_end_level:
            return int(pivot10 * (level_index / 10.0))

        pivot50 = int(pivot10 * (mid_end_level / 10.0))
        return int(pivot50 * ((level_index / mid_end_level) ** late_exp))

    def get_success_rate(
        self, level_index: int, cultivation_type: str = "灵修"
    ) -> float:
        """Return the base breakthrough success rate for a target level.

        The rate is looked up by the realm index of the target level. If the
        configured table is shorter than the realm index, the last value (floor)
        is used.

        Args:
            level_index: 1-based target level.
            cultivation_type: "灵修" or "体修".

        Returns:
            Base success rate as a float, clamped to ``[0.0, 1.0]``.
        """
        if level_index < 1:
            return 0.0

        config = self._get_level_config(cultivation_type)
        rates = config.get("success_rates", [])
        if not rates:
            return 0.4

        # Level 10 is the "initial" stage of the next realm, so it shares the
        # next realm's success rate (e.g. levels 10-19 use realm index 1).
        realm_index = level_index // 10
        if realm_index >= len(rates):
            realm_index = len(rates) - 1
        return max(0.0, min(1.0, float(rates[realm_index])))

    def get_failure_penalty_rate(self, cultivation_type: str = "灵修") -> float:
        """Return the breakthrough failure penalty rate for the given route.

        The penalty is expressed as a fraction of the current level's required
        EXP (``E(L) * rate``), not of the player's total experience.
        """
        config = self._get_level_config(cultivation_type)
        return float(config.get("failure_penalty_rate", 0.25))

    def get_level_index_by_name(
        self, level_name: str, cultivation_type: str | None = None
    ) -> int | None:
        """Reverse-lookup a 1-based level index from its display name.

        Searches the specified route; if none is specified, both routes are
        searched. "初期" names are included automatically.

        Args:
            level_name: The Chinese level name to resolve.
            cultivation_type: Optional route filter ("灵修" or "体修").

        Returns:
            The 1-based level index, or ``None`` if not found.
        """
        routes = [cultivation_type] if cultivation_type else ["灵修", "体修"]
        for route in routes:
            config = self._get_level_config(route)
            realms = config.get("realms", [])
            max_level = self._derive_max_level(realms)
            for level in range(1, max_level + 1):
                if self.get_level_name(level, route) == level_name:
                    return level
        return None

    def _load_level_config(self, file_path: Path) -> dict:
        """Load a new-style level configuration (dict with realms and formula)."""
        if not file_path.exists():
            logger.warning(f"境界配置文件 {file_path} 不存在，将使用空配置。")
            return {}
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                logger.info(f"成功加载境界配置 {file_path.name}（新结构）。")
                return data
            if isinstance(data, list):
                logger.warning(
                    f"境界配置 {file_path.name} 为旧版列表格式，请按新结构替换。"
                )
                return {}
            logger.error(f"境界配置 {file_path.name} 格式错误。")
            return {}
        except Exception as e:
            logger.error(f"加载境界配置 {file_path} 失败: {e}")
            return {}

    def _build_level_data(self, config: dict, cultivation_type: str) -> list[dict]:
        """Synthesize the legacy per-level list from the new-style config.

        This shim preserves compatibility with modules that still read
        ``level_data`` directly (e.g. boss_manager). Generated entries contain
        ``level``, ``level_name``, ``exp_needed`` and ``success_rate`` but no
        ``base_*`` attributes.
        """
        realms = config.get("realms", [])
        data: list[dict] = []
        if not realms:
            return data
        max_level = self._derive_max_level(realms)
        for level in range(1, max_level + 1):
            data.append(
                {
                    "level": level,
                    "level_name": self.get_level_name(level, cultivation_type),
                    "exp_needed": self.get_exp_needed(level, cultivation_type),
                    "success_rate": self.get_success_rate(level, cultivation_type),
                }
            )
        return data

    def _validate_level_configs(self):
        """Warn if the two cultivation routes have inconsistent realm counts."""
        spirit_count = len(self._level_config.get("realms", []))
        body_count = len(self._body_level_config.get("realms", []))
        if spirit_count and body_count and spirit_count != body_count:
            logger.warning(
                "灵修与体修的大境界数量不一致（灵修 %d，体修 %d），可能导致显示异常。",
                spirit_count,
                body_count,
            )

    def _load_json_data(self, file_path: Path) -> list[dict]:
        """加载JSON配置文件（列表格式）"""
        if not file_path.exists():
            logger.warning(f"数据文件 {file_path} 不存在，将使用空数据。")
            return []
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功加载 {file_path.name} (共 {len(data)} 条数据)。")
                return data
        except Exception as e:
            logger.error(f"加载数据文件 {file_path} 失败: {e}")
            return []

    def _load_config_with_default(self, file_path: Path, default_config: dict) -> dict:
        """加载配置，如果不存在则创建默认配置"""
        if not file_path.exists():
            try:
                # 确保目录存在
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                logger.info(f"创建默认配置文件: {file_path.name}")
                return default_config
            except Exception as e:
                logger.error(f"创建配置文件 {file_path} 失败: {e}")
                return default_config

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功加载配置文件: {file_path.name}")
                return data
        except Exception as e:
            logger.error(f"加载配置文件 {file_path} 失败: {e}")
            return default_config

    def _load_items_data(self, file_path: Path) -> dict[str, dict]:
        """加载物品配置文件并转换为字典（key为物品名称）

        支持三种顶层格式：
        - list: [{"name": ..., ...}, ...]
        - dict-of-dict: {"id": {"name": ..., ...}, ...}
        - dict-of-list: {"分组": [{"name": ..., ...}, ...], ...}
          展平为 name→definition 的字典，并在 definition 中注入 ``_group`` 字段保留分组。
        """
        if not file_path.exists():
            logger.warning(f"物品数据文件 {file_path} 不存在，将使用空数据。")
            return {}
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

                if isinstance(data, list):
                    items_dict = {
                        item.get("name", ""): item
                        for item in data
                        if isinstance(item, dict) and item.get("name")
                    }
                elif isinstance(data, dict):
                    items_dict = {}
                    for key, value in data.items():
                        if isinstance(value, dict) and value.get("name"):
                            # dict-of-dict entry
                            if "id" not in value:
                                value["id"] = key
                            items_dict[value["name"]] = value
                        elif isinstance(value, list):
                            # dict-of-list: flatten each item and remember its group
                            for item in value:
                                if isinstance(item, dict) and item.get("name"):
                                    item["_group"] = key
                                    if "id" not in item:
                                        item["id"] = item["name"]
                                    items_dict[item["name"]] = item
                        else:
                            logger.warning(
                                f"物品数据文件 {file_path} 中的键 {key} 格式不正确，已跳过。"
                            )
                else:
                    logger.error(
                        f"物品数据文件 {file_path} 格式不正确，应该是数组或字典。"
                    )
                    return {}

                logger.info(
                    f"成功加载 {file_path.name} (共 {len(items_dict)} 个物品)。"
                )
                return items_dict
        except Exception as e:
            logger.error(f"加载物品数据文件 {file_path} 失败: {e}")
            return {}

    def _load_all(self):
        """加载所有配置文件"""
        config_dir = self._base_dir / "config"

        # 加载新结构境界配置并合成运行时逐級列表（兼容 shim）
        self._level_config = self._load_level_config(config_dir / "level_config.json")
        self._body_level_config = self._load_level_config(
            config_dir / "body_level_config.json"
        )
        self.level_data = self._build_level_data(self._level_config, "灵修")
        self.body_level_data = self._build_level_data(self._body_level_config, "体修")
        self._validate_level_configs()

        # 加载物品配置
        self.items_data = self._load_items_data(config_dir / "items.json")
        self.weapons_data = self._load_items_data(config_dir / "weapons.json")
        self.pills_data = self._load_items_data(config_dir / "pills.json")
        self.exp_pills_data = self._load_items_data(config_dir / "exp_pills.json")
        self.utility_pills_data = self._load_items_data(
            config_dir / "utility_pills.json"
        )
        self.storage_rings_data = self._load_items_data(
            config_dir / "storage_rings.json"
        )

        # 加载新系统配置
        self.sect_config = self._load_config_with_default(
            config_dir / "sect_config.json", SECT_CONFIG
        )
        self.boss_config = self._load_config_with_default(
            config_dir / "boss_config.json", BOSS_CONFIG
        )
        self.rift_config = self._load_config_with_default(
            config_dir / "rift_config.json", RIFT_CONFIG
        )
        self.alchemy_config = self._load_config_with_default(
            config_dir / "alchemy_config.json", ALCHEMY_CONFIG
        )
        self.alchemy_recipes = self._load_items_data(
            config_dir / "alchemy_recipes.json"
        )

        # Load impart tier reward config (types 分表，缺失时用默认配置)
        self.impart_config = self._load_config_with_default(
            config_dir / "impart_config.json", IMPART_CONFIG
        )

        # 叙事文案配置（模板+变体池），加载后做插值变量契约校验
        self.narrative_config = self._load_config_with_default(
            config_dir / "narrative_config.json", DEFAULT_NARRATIVE_CONFIG
        )
        self._validate_narrative_config()

        # 灵根/体质评价大表（条目型配置，key为灵根名）
        self.spirit_root_descriptions = self._load_items_data(
            config_dir / "spirit_root_descriptions.json"
        )

        # 加载游戏配置（包含各系统的硬编码参数）
        self.game_config = self._load_config_with_default(
            config_dir / "game_config.json", {}
        )

        self._pill_names_cache = None

        # Load new skill system configs
        self.skills_data = self._load_items_data(config_dir / "skills.json")
        self.heart_methods_data = self._load_items_data(
            config_dir / "heart_methods.json"
        )

        # 加载宗门扩展配置（默认宗门定义 + 任务池），随后做结构校验
        self.sect_factions = self._load_config_with_default(
            config_dir / "sect_factions.json", SECT_FACTIONS
        )
        self.sect_tasks = self._load_config_with_default(
            config_dir / "sect_tasks.json", SECT_TASKS
        )
        self._validate_sect_configs()

        logger.info(
            f"配置管理器初始化完成，"
            f"加载了 {len(self.level_data)} 个灵修境界配置，"
            f"{len(self.body_level_data)} 个体修境界配置，"
            f"{len(self.skills_data)} 个技能配置，"
            f"{len(self.heart_methods_data)} 个心法配置，"
            f"{len(self.impart_config.get('types', {}))} 类传承等阶，"
            f"以及新系统配置 (宗门/Boss/秘境/炼丹)"
        )

    def is_pill(self, item_name: str) -> bool:
        """检查物品是否为丹药类型（统一的丹药判断方法）"""
        if item_name in self.pills_data:
            return True
        if item_name in self.exp_pills_data:
            return True
        if item_name in self.utility_pills_data:
            return True

        item_config = self.items_data.get(item_name)
        if item_config and item_config.get("type") == "丹药":
            return True

        return False

    def get_all_pill_names(self) -> set:
        """获取所有注册的丹药名称"""
        if self._pill_names_cache is not None:
            return self._pill_names_cache

        pill_names = set()
        pill_names.update(self.pills_data.keys())
        pill_names.update(self.exp_pills_data.keys())
        pill_names.update(self.utility_pills_data.keys())

        for name, item in self.items_data.items():
            if isinstance(item, dict) and item.get("type") == "丹药":
                pill_names.add(name)

        self._pill_names_cache = pill_names
        return pill_names

    def invalidate_cache(self):
        """清除缓存，在配置重载时调用"""
        self._pill_names_cache = None

    def _validate_narrative_config(self):
        """Validate narrative template variable contracts against declared scenes.

        For every scene declared in ``NARRATIVE_SCENE_VARS``, each configured
        template (all three shapes, including bucketed pools and route-tagged
        entries) may only reference variables the code render point declares.
        A violating scene is replaced with the embedded default so the plugin
        keeps running; the error log names the scene key, location, and
        offending variables. Unknown bucket keys only warn — the content side
        may pre-fill buckets for segments the code does not select yet. The
        embedded defaults themselves are validated too, as a dev-time safety
        net (a broken default has nothing left to fall back to).
        """
        for section, scenes in NARRATIVE_SCENE_VARS.items():
            for scene, declared in scenes.items():
                default_value = DEFAULT_NARRATIVE_CONFIG.get(section, {}).get(scene)
                if default_value is not None:
                    self._check_narrative_scene(
                        section, scene, default_value, declared, source="内嵌默认"
                    )

            section_cfg = self.narrative_config.get(section)
            if not isinstance(section_cfg, dict):
                continue
            for scene, declared in scenes.items():
                if scene not in section_cfg:
                    continue
                if not self._check_narrative_scene(
                    section, scene, section_cfg[scene], declared, source="配置"
                ):
                    section_cfg[scene] = DEFAULT_NARRATIVE_CONFIG.get(section, {}).get(
                        scene
                    )

    def _check_narrative_scene(
        self, section: str, scene: str, value: Any, declared: set[str], source: str
    ) -> bool:
        """Check one scene value against its declared variable contract.

        Returns True when the scene is usable. Violations are logged with the
        scene key, entry location, and offending variable names.
        """
        ok = True
        if isinstance(value, dict) and not isinstance(value.get("text"), str):
            for bucket in value:
                if bucket not in NARRATIVE_BUCKET_KEYS:
                    logger.warning(
                        f"叙事配置[{source}] {section}.{scene} 存在未知分桶键 "
                        f"{bucket!r}，该桶不会被取用（合法桶键: {NARRATIVE_BUCKET_KEYS}）。"
                    )

        for location, entry in _iter_scene_entries(value):
            if isinstance(entry, dict):
                tagged_route = entry.get("route")
                if tagged_route and tagged_route not in _NARRATIVE_ROUTES:
                    logger.warning(
                        f"叙事配置[{source}] {section}.{scene}{location} 存在未知路线标注 "
                        f"{tagged_route!r}（合法值: {_NARRATIVE_ROUTES}）。"
                    )
                template = entry.get("text")
                if not isinstance(template, str):
                    logger.error(
                        f"叙事配置[{source}] {section}.{scene}{location} 条目缺少 text 字段。"
                    )
                    ok = False
                    continue
            else:
                template = entry
            try:
                used = extract_template_vars(template)
            except ValueError as exc:
                logger.error(
                    f"叙事文案契约违例[{source}] {section}.{scene}{location}: "
                    f"模板花括号不配对（{exc}）。"
                )
                ok = False
                continue
            unknown = used - declared
            if unknown:
                logger.error(
                    f"叙事文案契约违例[{source}] {section}.{scene}{location}: "
                    f"未知变量 {sorted(unknown)}，该场景已声明变量 {sorted(declared)}。"
                )
                ok = False
        return ok

    def _validate_sect_configs(self):
        """Validate sect_factions/sect_tasks structure and cross-references.

        Checks required fields (id/name) and that referenced skill pools,
        heart methods, and weapon IDs exist in their respective configs.
        Problems are logged as warnings without interrupting loading.
        """
        skill_pools = {
            s.get("_group")
            for s in self.skills_data.values()
            if isinstance(s, dict) and s.get("_group")
        }
        heart_method_ids = {
            h.get("id")
            for h in self.heart_methods_data.values()
            if isinstance(h, dict) and h.get("id")
        }
        weapon_ids = {
            w.get("id")
            for w in self.weapons_data.values()
            if isinstance(w, dict) and w.get("id")
        }

        factions = self.sect_factions.get("factions", [])
        if not isinstance(factions, list):
            logger.warning("sect_factions.json 的 factions 字段应为列表，已跳过校验。")
            factions = []

        faction_ids: set = set()
        for faction in factions:
            if not isinstance(faction, dict):
                logger.warning(
                    f"sect_factions.json 存在非对象条目，已跳过: {faction!r}"
                )
                continue
            fid, name = faction.get("id"), faction.get("name")
            if not fid or not name:
                logger.warning(
                    f"sect_factions.json 条目缺少必填字段 id/name: {faction!r}"
                )
                continue
            faction_ids.add(fid)

            pool = faction.get("skill_pool")
            if pool and isinstance(pool, str) and pool not in skill_pools:
                logger.warning(
                    f"宗门 {fid} 引用的功法池 {pool} 在 skills.json 中不存在。"
                )
            for hm_id in faction.get("heart_methods", []):
                if hm_id not in heart_method_ids:
                    logger.warning(
                        f"宗门 {fid} 引用的心法 {hm_id} 在 heart_methods.json 中不存在。"
                    )
            for treasure in faction.get("treasures", []):
                tid = treasure.get("id") if isinstance(treasure, dict) else None
                if (
                    isinstance(treasure, dict)
                    and treasure.get("type") == "weapon"
                    and tid not in weapon_ids
                ):
                    logger.warning(
                        f"宗门 {fid} 引用的宗门之宝 {tid} 在 weapons.json 中不存在。"
                    )

        for task in self.sect_tasks.get("construction_tasks", []):
            if not isinstance(task, dict) or not task.get("id") or not task.get("name"):
                logger.warning(
                    f"sect_tasks.json 建设任务缺少必填字段 id/name: {task!r}"
                )

        for chain in self.sect_tasks.get("master_task_chains", []):
            if not isinstance(chain, dict):
                logger.warning(f"sect_tasks.json 师承任务链存在非对象条目: {chain!r}")
                continue
            cid, sid = chain.get("id"), chain.get("sect_id")
            if not cid or not sid:
                logger.warning(
                    f"sect_tasks.json 师承任务链缺少必填字段 id/sect_id: {chain!r}"
                )
                continue
            if faction_ids and sid not in faction_ids:
                logger.warning(
                    f"师承任务链 {cid} 引用的宗门 {sid} 在 sect_factions.json 中不存在。"
                )
            for stage in chain.get("stages", []):
                if not isinstance(stage, dict):
                    continue
                reward = stage.get("reward")
                chance_pool = (
                    reward.get("skill_learn_chance")
                    if isinstance(reward, dict)
                    else None
                )
                if (
                    chance_pool
                    and isinstance(chance_pool, str)
                    and chance_pool not in skill_pools
                ):
                    logger.warning(
                        f"师承任务链 {cid} 阶段「{stage.get('name', '?')}」引用的功法池 "
                        f"{chance_pool} 在 skills.json 中不存在。"
                    )
