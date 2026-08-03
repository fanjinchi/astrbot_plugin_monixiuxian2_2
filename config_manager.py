import json
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .data.default_configs import ALCHEMY_CONFIG, BOSS_CONFIG, RIFT_CONFIG, SECT_CONFIG

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

        # Load new system configs
        self.skills_data: dict[str, dict] = {}  # Skill definitions
        self.heart_methods_data: dict[str, dict] = {}  # Heart method definitions
        self.impart_config: dict[str, Any] = {}  # Impart tier rewards

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

        # Load impart tier reward config
        self.impart_config = self._load_config_with_default(
            config_dir / "impart_config.json", {}
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

        logger.info(
            f"配置管理器初始化完成，"
            f"加载了 {len(self.level_data)} 个灵修境界配置，"
            f"{len(self.body_level_data)} 个体修境界配置，"
            f"{len(self.skills_data)} 个技能配置，"
            f"{len(self.heart_methods_data)} 个心法配置，"
            f"{len(self.impart_config.get('tiers', []))} 个传承等阶，"
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
