# managers/rift_manager.py
"""
秘境系统管理器 - 处理秘境探索、奖励等逻辑
"""

import importlib.util
import os
import random
import sys
import time
from typing import TYPE_CHECKING

# 绝对导入（已安装包）：不依赖相对导入链，standalone 测试加载同样可用，
# 与 adventure_manager.py:15 的先例一致
from astrbot.api import logger

try:
    from ..core.encounter_store import (
        KIND_BEAST,
        KIND_LEGACY,
        KIND_PUZZLE,
        EncounterStore,
    )
    from ..core.rift_puzzle_manager import CheckResult
    from ..core.rift_puzzle_manager import generate as generate_rift_puzzle
    from ..data.data_manager import DataBase
    from ..data.default_configs import RIFT_CONFIG
    from ..managers.enemy_manager import EnemyManager  # noqa: F401
    from ..managers.pve_combat_manager import PVECombatManager
    from ..models import Player
    from ..models_extended import UserStatus
    from ..utils.narrative_text import render_narrative
except ImportError:
    # 独立运行（测试）时降级加载依赖
    def _load_module(name, rel_path):
        """Import a plugin module by file path so this file can run standalone under tests."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def _load_default_configs():
        """Load data/default_configs.py under a synthetic package.

        default_configs relatively imports its narrative_defaults package, so
        the plain file-path loader above cannot satisfy it; a synthetic parent
        package gives the relative import a resolution context.
        """
        import types

        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pkg_name = "rift_manager_standalone_data"
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [os.path.join(plugin_root, "data")]
            sys.modules[pkg_name] = pkg
        full_name = f"{pkg_name}.default_configs"
        if full_name in sys.modules:
            return sys.modules[full_name]
        path = os.path.join(plugin_root, "data", "default_configs.py")
        spec = importlib.util.spec_from_file_location(full_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        return mod

    DataBase = object
    _pve = _load_module("pve_combat_manager", "managers/pve_combat_manager.py")
    PVECombatManager = _pve.PVECombatManager
    _md = _load_module("models", "models.py")
    Player = _md.Player
    _mde = _load_module("models_extended", "models_extended.py")
    UserStatus = _mde.UserStatus
    _nt = _load_module("narrative_text", "utils/narrative_text.py")
    render_narrative = _nt.render_narrative
    RIFT_CONFIG = _load_default_configs().RIFT_CONFIG
    _es = _load_module("encounter_store", "core/encounter_store.py")
    EncounterStore = _es.EncounterStore
    KIND_PUZZLE = _es.KIND_PUZZLE
    KIND_BEAST = _es.KIND_BEAST
    KIND_LEGACY = _es.KIND_LEGACY
    _rpm = _load_module("rift_puzzle_manager", "core/rift_puzzle_manager.py")
    generate_rift_puzzle = _rpm.generate
    CheckResult = _rpm.CheckResult

if TYPE_CHECKING:
    from ..core import StorageRingManager

# 谜题作答形式提示（按谜题族；invalid 输入不耗次数，design D3）
_PUZZLE_ANSWER_FORM_HINTS = {
    "wuxing": "金/木/水/火/土 之一（单字）",
    "luoshu": "一个数字",
    "turtle": "甲/乙/丙 之一（单字）",
}


class RiftManager:
    """秘境系统管理器"""

    # 默认秘境探索时长（秒）
    DEFAULT_DURATION = 1800

    # 秘境物品掉落表（按秘境等级分组）
    RIFT_DROP_TABLE = {
        1: [  # 低级秘境
            {"name": "灵草", "weight": 40, "min": 2, "max": 5},
            {"name": "精铁", "weight": 30, "min": 1, "max": 3},
            {"name": "灵石碎片", "weight": 30, "min": 3, "max": 8},
        ],
        2: [  # 中级秘境
            {"name": "灵草", "weight": 30, "min": 3, "max": 7},
            {"name": "玄铁", "weight": 25, "min": 2, "max": 4},
            {"name": "灵兽毛皮", "weight": 20, "min": 1, "max": 3},
            {"name": "功法残页", "weight": 15, "min": 1, "max": 1},
            {"name": "秘境精华", "weight": 10, "min": 1, "max": 2},
        ],
        3: [  # 高级秘境
            {"name": "玄铁", "weight": 25, "min": 3, "max": 6},
            {"name": "星辰石", "weight": 20, "min": 2, "max": 4},
            {"name": "灵兽内丹", "weight": 20, "min": 1, "max": 2},
            {"name": "功法残页", "weight": 20, "min": 1, "max": 2},
            {"name": "天材地宝", "weight": 15, "min": 1, "max": 1},
        ],
    }

    # 秘境稀有丹药掉落表（按秘境等级分组，低概率掉落通用增益丹）
    RIFT_PILL_DROP_TABLE = {
        1: [  # 低级秘境 - 3%概率掉落
            {"name": "三品凝神增益丹", "weight": 100, "min": 1, "max": 1},
        ],
        2: [  # 中级秘境 - 5%概率掉落
            {"name": "三品凝神增益丹", "weight": 50, "min": 1, "max": 1},
            {"name": "四品破境增益丹", "weight": 40, "min": 1, "max": 1},
            {"name": "五品渡劫增益丹", "weight": 10, "min": 1, "max": 1},
        ],
        3: [  # 高级秘境 - 10%概率掉落
            {"name": "四品破境增益丹", "weight": 40, "min": 1, "max": 1},
            {"name": "五品渡劫增益丹", "weight": 30, "min": 1, "max": 1},
            {"name": "六品破境增益丹", "weight": 20, "min": 1, "max": 1},
            {"name": "七品化神增益丹", "weight": 10, "min": 1, "max": 1},
        ],
    }

    # 秘境丹药掉落概率（百分比）
    RIFT_PILL_DROP_CHANCE = {
        1: 3,  # 低级秘境 3%
        2: 5,  # 中级秘境 5%
        3: 10,  # 高级秘境 10%
    }

    def __init__(
        self,
        db: DataBase,
        config_manager=None,
        storage_ring_manager: "StorageRingManager" = None,
        pve_combat_mgr: PVECombatManager = None,
        encounter_store: "EncounterStore | None" = None,
    ):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.pve_combat_mgr = pve_combat_mgr
        # 传承管理器：可选注入（main.py 装配后），用于秘境触发传承机缘
        self.impart_mgr = None
        # 遭遇存储：可选注入共享单例（main.py 装配，与 AdventureManager 共用，
        # design D8）；默认自建，保证既有测试/独立使用不炸
        self.encounter_store = (
            encounter_store if encounter_store is not None else EncounterStore()
        )
        self.config = config_manager.rift_config if config_manager else {}
        self.explore_duration = self.config.get(
            "default_duration", self.DEFAULT_DURATION
        )

    def _get_level_name(self, level_index: int) -> str:
        """获取境界名称，统一委托给 ConfigManager 中央 API。"""
        if self.config_manager:
            return self.config_manager.get_level_name(level_index, "灵修")
        return f"境界{level_index}"

    def _get_rift_config_entry(self, rift_id: int) -> dict | None:
        """Look up the static rift_config.json entry for a rift id (carries sect_id/access)."""
        for entry in (self.config or {}).get("rifts", []):
            if isinstance(entry, dict) and entry.get("id") == rift_id:
                return entry
        return None

    async def _get_player_faction_id(self, player: Player) -> str | None:
        """Resolve the faction_id of the player's sect (None when sectless or a player-built sect)."""
        sect_id = getattr(player, "sect_id", 0)
        if not isinstance(sect_id, int) or not sect_id:
            return None
        if self.db is None or self.db.ext is None:
            return None
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect is None:
            return None
        return getattr(sect, "faction_id", None)

    async def _check_rift_access(
        self, player: Player, rift_id: int
    ) -> tuple[bool, str]:
        """Validate sect-exclusive access: rifts with sect_id + access=sect_member only admit that sect's members."""
        entry = self._get_rift_config_entry(rift_id)
        if not entry:
            return True, ""
        if not entry.get("sect_id") or entry.get("access") != "sect_member":
            return True, ""
        faction_id = await self._get_player_faction_id(player)
        if faction_id == entry.get("sect_id"):
            return True, ""
        return False, f"❌ 【{entry.get('name', '该秘境')}】仅对本宗弟子开放！"

    async def list_rifts(self, user_id: str = "") -> tuple[bool, str]:
        """
        列出秘境（宗门专属秘境仅本宗成员可见，非本宗成员列表直接过滤）

        Returns:
            (成功标志, 消息)
        """
        rifts = await self.db.ext.get_all_rifts()

        if not rifts:
            return False, "❌ 当前没有开放的秘境！"

        faction_id = None
        if user_id:
            player = await self.db.get_player_by_id(user_id)
            if player:
                faction_id = await self._get_player_faction_id(player)

        # 宗门专属秘境（sect_id + access=sect_member）仅本宗成员可见；
        # 非本宗直接过滤不展示，准入校验 _check_rift_access 仍作兜底
        visible_rifts = []
        for rift in rifts:
            entry = self._get_rift_config_entry(rift.rift_id)
            if (
                entry
                and entry.get("sect_id")
                and entry.get("access") == "sect_member"
                and faction_id != entry.get("sect_id")
            ):
                continue
            visible_rifts.append((rift, entry))

        if not visible_rifts:
            return False, "❌ 当前没有开放的秘境！"

        msg = "🌀 秘境列表\n"
        msg += "━━━━━━━━━━━━━━━\n"

        for rift, entry in visible_rifts:
            rewards_dict = rift.get_rewards()
            exp_range = rewards_dict.get("exp", [0, 0])
            gold_range = rewards_dict.get("gold", [0, 0])
            level_name = self._get_level_name(rift.required_level)

            msg += f"【{rift.rift_name}】(ID:{rift.rift_id})\n"
            # 入口叙事位（config-only，design D3）：旧配置无 description 字段按空处理
            description = (entry or {}).get("description") or ""
            if description:
                msg += f"  {description}\n"
            if entry and entry.get("sect_id") and entry.get("access") == "sect_member":
                msg += "  🏯 宗门专属秘境\n"
            if rift.required_level == 0:
                msg += "  等级要求：无限制\n"
            else:
                msg += f"  等级要求：{level_name} 及以上\n"
            msg += f"  修为奖励：{exp_range[0]:,}-{exp_range[1]:,}\n"
            msg += f"  灵石奖励：{gold_range[0]:,}-{gold_range[1]:,}\n\n"

        msg += "💡 使用 /探索秘境 <ID> 进入（如：/探索秘境 1）"

        return True, msg

    async def enter_rift(self, user_id: str, rift_id: int) -> tuple[bool, str]:
        """
        进入秘境

        Args:
            user_id: 用户ID
            rift_id: 秘境ID

        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        # 2. 检查用户状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)

        if user_cd.type != UserStatus.IDLE:
            return (
                False,
                f"❌ 你当前正{UserStatus.get_name(user_cd.type)}，无法探索秘境！",
            )

        # 3. 检查秘境
        rift = await self.db.ext.get_rift_by_id(rift_id)
        if not rift:
            return False, "❌ 秘境不存在！使用 /秘境列表 查看可用秘境"

        # 3.5 宗门专属秘境准入校验
        access_ok, access_msg = await self._check_rift_access(player, rift_id)
        if not access_ok:
            return False, access_msg

        # 4. 检查境界要求
        if player.level_index < rift.required_level:
            level_name = self._get_level_name(rift.required_level)
            return False, f"❌ 探索【{rift.rift_name}】需要达到【{level_name}】！"

        # 5. 设置探索状态，存储秘境ID
        scheduled_time = int(time.time()) + self.explore_duration
        extra_data = {"rift_id": rift_id, "rift_level": rift.rift_level}
        await self.db.ext.set_user_busy(
            user_id, UserStatus.EXPLORING, scheduled_time, extra_data
        )

        return (
            True,
            f"✨ 你进入了『{rift.rift_name}』！探索需要 {self.explore_duration // 60} 分钟。\n使用 /完成探索 领取奖励",
        )

    async def finish_exploration(self, user_id: str) -> tuple[bool, str, dict | None]:
        """
        完成秘境探索

        Args:
            user_id: 用户ID

        Returns:
            (成功标志, 消息, 奖励数据)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        # 2. 检查CD状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 你当前不在探索秘境！", None

        # 3. 检查时间
        current_time = int(time.time())
        if current_time < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - current_time
            minutes = remaining // 60
            return False, f"❌ 探索尚未完成！还需要 {minutes} 分钟。", None

        # 4. 获取秘境信息（从extra_data中读取）
        extra_data = (
            user_cd.get_extra_data() if hasattr(user_cd, "get_extra_data") else {}
        )
        rift_id = extra_data.get("rift_id", 0)
        rift_level = extra_data.get("rift_level", 1)

        # 获取秘境配置
        rift = await self.db.ext.get_rift_by_id(rift_id) if rift_id else None
        rift_name = rift.rift_name if rift else "未知秘境"

        # 5. 根据秘境配置计算奖励
        if rift:
            rewards_config = rift.get_rewards()
            exp_range = rewards_config.get("exp", [1000, 5000])
            gold_range = rewards_config.get("gold", [500, 2000])
            exp_reward = random.randint(exp_range[0], exp_range[1])
            gold_reward = random.randint(gold_range[0], gold_range[1])
            rift_level = rift.rift_level
        else:
            # 兼容旧数据，使用默认奖励
            exp_reward = random.randint(1000, 5000)
            gold_reward = random.randint(500, 2000)

        # 随机事件：变体池外移至 rift 配置顶层 explore_events（design D3，字段
        # 结构沿用原硬编码 desc/item_chance）；旧配置缺该键时回落 RIFT_CONFIG 默认池
        events = self.config.get("explore_events") or RIFT_CONFIG.get(
            "explore_events", []
        )
        event = random.choice(events) if events else {"desc": "", "item_chance": 0}

        # 6. 物品掉落（根据秘境等级）。
        # 结算不再自动触发 PvE（add-rift-encounters design D5），基础奖励不被
        # 战斗修改，掉落恒按事件 item_chance roll；妖兽战斗移至「探索秘境 迎战」
        # 应邀路径（accept_beast_challenge）
        dropped_items = await self._roll_rift_drops(
            player, rift_level, event["item_chance"]
        )
        item_msg = await self._store_dropped_items(player, dropped_items)

        # 6.5 传承机缘：命中 legacy_chance 改为挂起传承之地 pending 遭遇
        # （应邀制，design D8），不再内联自动挑战守护者
        legacy_msg = ""
        legacy_chance = float(self.config.get("legacy_chance", 0.0))
        if (
            self.impart_mgr
            and self.pve_combat_mgr
            and legacy_chance > 0
            and random.random() < legacy_chance
        ):
            legacy_msg = self._pend_legacy_encounter(
                player.user_id, legacy_type="rift", source="rift"
            )

        # 7. 应用奖励
        player.experience += exp_reward
        player.gold += gold_reward
        await self.db.update_player(player)

        # 8. 清除CD
        await self.db.ext.set_user_free(user_id)

        # 8.5 结算后遭遇判定（design D4）：谜题/妖兽独立判定、不互斥，
        # 触发则挂起 pending 并把题面/提示拼进结算消息。
        # 可选概率功能：异常降级为日志，绝不中断结算回复（此时奖励已入账、
        # CD 已清；同历练传承路径 adventure_manager.py:304 的降级先例）
        encounter_msg = ""
        try:
            encounter_msg = self._roll_encounters(
                player, rift_id, rift_level, exp_reward
            )
        except Exception as exc:
            logger.error(f"秘境结算遭遇判定失败: {exc}")

        # 结算叙事位（config-only，design D3）：空串时输出与旧版逐字一致
        rift_entry = self._get_rift_config_entry(rift_id)
        settlement_desc = (rift_entry or {}).get("settlement_desc") or ""
        settlement_line = f"{settlement_desc}\n\n" if settlement_desc else ""

        msg = f"""
🌀 探索完成 - {rift_name}
━━━━━━━━━━━━━━━

{settlement_line}{event["desc"]}

获得修为：+{exp_reward:,}
获得灵石：+{gold_reward:,}{item_msg}{legacy_msg}{encounter_msg}
        """.strip()

        reward_data = {
            "exp": exp_reward,
            "gold": gold_reward,
            "event": event["desc"],
            "items": dropped_items,
            "rift_name": rift_name,
            # 结算不再有战斗，pve_won 恒 False（design D5）；迎战胜利的计数在
            # main.py 迎战分支消费。键必须保留：main.py 与 gm_manager 强制结算
            # 路径均读取它推进师承 win_pve
            "pve_won": False,
        }

        return True, msg, reward_data

    async def exit_rift(self, user_id: str) -> tuple[bool, str]:
        """
        退出秘境（放弃探索）

        Args:
            user_id: 用户ID

        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        # 2. 检查CD状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 你当前不在探索秘境！"

        # 3. 清除CD状态
        await self.db.ext.set_user_free(user_id)

        return True, "✅ 你已退出秘境，本次探索未获得任何奖励。"

    # -------- 遭遇机制（add-rift-encounters） --------

    def _encounter_ttl(self) -> int:
        """pending 遭遇 TTL（秒）。

        存量 rift_config.json 不会被自动合并新键，按 explore_events 先例回落
        RIFT_CONFIG 默认值（design D4 存量兼容），防止读到 None。
        """
        return int(
            self.config.get(
                "encounter_ttl_seconds", RIFT_CONFIG.get("encounter_ttl_seconds", 600)
            )
        )

    def _puzzle_attempts(self) -> int:
        """谜题作答机会次数，缺键回落 RIFT_CONFIG 默认（同 _encounter_ttl）。"""
        return int(
            self.config.get("puzzle_attempts", RIFT_CONFIG.get("puzzle_attempts", 2))
        )

    def _pend_puzzle_encounter(
        self, player: Player, rift_level: int, exp_base: int
    ) -> str:
        """挂起古阵谜题遭遇并返回结算提示段（题面 + 作答指引）。

        payload 携带 RiftPuzzle 本体与奖励上下文（rift_level/修为基数）——
        RiftPuzzle 不含奖励上下文，由 EncounterStore 条目携带（design D6）。
        """
        puzzle = generate_rift_puzzle(attempts=self._puzzle_attempts())
        self.encounter_store.pend(
            player.user_id,
            KIND_PUZZLE,
            {"puzzle": puzzle, "rift_level": rift_level, "exp_base": exp_base},
            ttl=self._encounter_ttl(),
        )
        return (
            "\n\n🧩 你触动了一座古阵的禁制，碑纹亮起：\n"
            f"{puzzle.question_text}\n"
            f"💡 发送「探索秘境 破阵 <答案>」破阵（{puzzle.attempts_left} 次机会；"
            "不响应则机缘自行消散）"
        )

    def _pend_beast_encounter(
        self, player: Player, rift_level: int, enemy_group: str | None
    ) -> str:
        """挂起妖兽拦路遭遇并返回结算提示段。

        payload 记录 rift_level 与 enemy_group（秘境条目的定向怪物组 key，
        None 表示回落全局池），供迎战时使用（design D5）。
        """
        self.encounter_store.pend(
            player.user_id,
            KIND_BEAST,
            {"rift_level": rift_level, "enemy_group": enemy_group},
            ttl=self._encounter_ttl(),
        )
        return (
            "\n\n⚔️ 一头妖兽拦住了你的去路！\n"
            "💡 发送「探索秘境 迎战」与之搏斗（不响应则机缘自行消散，无任何损失）"
        )

    def _pend_legacy_encounter(
        self, user_id: str, legacy_type: str, source: str
    ) -> str:
        """挂起传承之地遭遇并返回结算提示段（应邀制，design D8）。

        payload 记录 legacy_type（应邀胜利时 create_legacy 的类型）与 source
        （rift/adventure 来源，信息位）。
        """
        self.encounter_store.pend(
            user_id,
            KIND_LEGACY,
            {"legacy_type": legacy_type, "source": source},
            ttl=self._encounter_ttl(),
        )
        # 提示文案与 AdventureManager._maybe_trigger_legacy 保持逐字一致
        # （两处各写一份，避免为单行文案引入跨管理器依赖）
        return (
            "\n\n🗿 你偶遇上古传承之地，传承禁制悄然开启。\n"
            "💡 发送「探索秘境 传承」应邀挑战守护者（不响应则机缘自行消散，无任何惩罚）"
        )

    def _roll_encounters(
        self, player: Player, rift_id: int, rift_level: int, exp_base: int = 0
    ) -> str:
        """结算后独立判定谜题/妖兽遭遇（design D4）。

        顶层 puzzle_rate/beast_rate 为默认触发率；秘境条目存在 encounter_rate
        时覆盖两者。两类判定相互独立、不互斥（可同时触发）。传承之地遭遇不走
        本方法：沿用 finish_exploration 的 legacy_chance 触发（design D4/D8）。

        Returns:
            追加到结算消息末尾的遭遇段落（均未触发时为空串）。
        """
        entry = self._get_rift_config_entry(rift_id) or {}
        override = entry.get("encounter_rate")
        if override is not None:
            puzzle_rate = beast_rate = float(override)
        else:
            # 存量配置缺新键时回落 RIFT_CONFIG 默认（design D4 存量兼容）
            puzzle_rate = float(
                self.config.get("puzzle_rate", RIFT_CONFIG.get("puzzle_rate", 0.3))
            )
            beast_rate = float(
                self.config.get("beast_rate", RIFT_CONFIG.get("beast_rate", 0.5))
            )
        sections = []
        if puzzle_rate > 0 and random.random() < puzzle_rate:
            sections.append(self._pend_puzzle_encounter(player, rift_level, exp_base))
        if beast_rate > 0 and random.random() < beast_rate:
            sections.append(
                self._pend_beast_encounter(player, rift_level, entry.get("enemy_group"))
            )
        return "".join(sections)

    async def _store_dropped_items(
        self, player: Player, dropped_items: list[tuple[str, int]]
    ) -> str:
        """把掉落列表入库（丹药背包/储物戒）并组装消息段。

        抽取自 finish_exploration 原内联块（design D5），供结算/破阵/迎战
        三处复用，否则谜题与迎战奖励会被 roll 出但静默丢失。

        Returns:
            "📦 获得物品" 消息段；无掉落时为空串。
        """
        if not dropped_items:
            return ""
        item_lines = []
        for item_name, count in dropped_items:
            # 检查是否为丹药，丹药存入丹药背包，其他存入储物戒
            is_pill = self._is_pill_item(item_name)
            if is_pill:
                # 存入丹药背包
                inventory = player.get_pills_inventory()
                inventory[item_name] = inventory.get(item_name, 0) + count
                player.set_pills_inventory(inventory)
                item_lines.append(f"  · {item_name} x{count}（丹药背包）")
            elif self.storage_ring_manager:
                success, _ = await self.storage_ring_manager.store_item(
                    player, item_name, count, silent=True
                )
                if success:
                    item_lines.append(f"  · {item_name} x{count}")
                else:
                    item_lines.append(f"  · {item_name} x{count}（储物戒已满，丢失）")
            else:
                item_lines.append(f"  · {item_name} x{count}（无法存储）")
        if item_lines:
            return "\n\n📦 获得物品：\n" + "\n".join(item_lines)
        return ""

    async def answer_puzzle(self, user_id: str, answer: str) -> tuple[bool, str]:
        """回应当前 pending 的古阵谜题（「探索秘境 破阵 <答案>」）。

        答对：一次掉落 roll（item_chance=100，与秘境掉落同规则）入库 +
        修为基数 × 0.2 取整（design D6）；答错耗一次机会并提示剩余；
        形式非法（按谜题族判定）不耗机会；机会耗尽关闭谜题、零惩罚。

        Returns:
            (是否答对, 消息)。无 pending/已过期/热重载丢失 →
            (False, 机缘已消散提示)。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        entry = self.encounter_store.get_active(user_id, KIND_PUZZLE)
        if entry is None:
            return (
                False,
                "🌀 当前没有待破解的古阵谜题（机缘已消散；完成探索有概率触发）。",
            )

        puzzle = entry.payload["puzzle"]
        result = puzzle.check(answer)
        # CheckResult 是 str Enum，用 == 比较：测试独立加载场景下谜题与本模块
        # 可能各持一份枚举类，== 按值相等兜底（生产环境恒为同一类）
        if result == CheckResult.INVALID:
            hint = _PUZZLE_ANSWER_FORM_HINTS.get(puzzle.family, "符合题意的形式")
            return False, f"⚠️ 答案形式不对（须为{hint}），本次不消耗破阵机会。"
        if result == CheckResult.WRONG:
            if puzzle.attempts_left > 0:
                return (
                    False,
                    f"❌ 碑纹黯淡了一瞬——答案不对。剩余机会：{puzzle.attempts_left} 次。",
                )
            # 机会耗尽：关闭谜题，零惩罚（design D6）
            self.encounter_store.consume(user_id, KIND_PUZZLE)
            return False, "💨 机会耗尽，古阵重归沉寂。机缘已消散（无任何惩罚）。"

        # 答对：消耗遭遇，发放奖励
        self.encounter_store.consume(user_id, KIND_PUZZLE)
        rift_level = int(entry.payload.get("rift_level", 1))
        exp_base = int(entry.payload.get("exp_base", 0))
        bonus_exp = int(exp_base * 0.2)  # design D6：修为基数 × 0.2 取整
        dropped_items = await self._roll_rift_drops(player, rift_level, 100)
        item_msg = await self._store_dropped_items(player, dropped_items)
        player.experience += bonus_exp
        await self.db.update_player(player)
        return True, f"✅ 碑纹大亮，古阵应声而解！\n获得修为：+{bonus_exp:,}{item_msg}"

    async def accept_beast_challenge(self, user_id: str) -> tuple[bool, str, dict]:
        """接受当前 pending 的妖兽挑战（「探索秘境 迎战」）。

        战斗由 pve_combat_mgr.challenge_rift_beast 完成；本方法只组装奖励
        （design D5）：胜利 = 敌人修为入账 + 一次掉落 roll 入库，结果数据携带
        pve_won=True（main.py 迎战分支据此推进师承 win_pve 计数）；失败/平局
        视同挑战失败——hp=1（战斗层写回）、机缘消耗，不动已发的基础结算奖励。

        Returns:
            (是否受理并完成战斗, 消息, 结果数据)。结果数据恒含 pve_won
            （仅战斗胜利为 True）；无 pending/已过期/系统异常 →
            (False, 提示, {"pve_won": False})。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", {"pve_won": False}
        if not self.pve_combat_mgr:
            return False, "❌ 战斗系统未就绪，请稍后再试。", {"pve_won": False}

        entry = self.encounter_store.get_active(user_id, KIND_BEAST)
        if entry is None:
            return (
                False,
                "🌀 当前没有可迎战的妖兽（机缘已消散；完成探索有概率触发）。",
                {"pve_won": False},
            )

        rift_level = int(entry.payload.get("rift_level", 1))
        enemy_group = entry.payload.get("enemy_group")
        outcome = await self.pve_combat_mgr.challenge_rift_beast(player, enemy_group)
        if outcome is None:
            # 敌人生成失败属系统异常：保留 pending 供稍后重试，不消耗机缘
            return False, "❌ 妖兽遭遇异常，请稍后再试。", {"pve_won": False}

        # 战斗已发生，无论胜负机缘均消耗（spec：迎战失败/平局机缘消耗）
        self.encounter_store.consume(user_id, KIND_BEAST)
        won, _is_draw, battle_msg, enemy_exp = outcome

        if won:
            player.experience += enemy_exp
            dropped_items = await self._roll_rift_drops(player, rift_level, 100)
            item_msg = await self._store_dropped_items(player, dropped_items)
            await self.db.update_player(player)
            msg = f"{battle_msg}\n\n🎁 迎战奖励：修为 +{enemy_exp:,}{item_msg}"
            return (
                True,
                msg,
                {"pve_won": True, "exp": enemy_exp, "items": dropped_items},
            )

        # 失败/平局：hp=1 已由战斗层写回，落库即可；基础结算奖励不受影响
        await self.db.update_player(player)
        msg = f"{battle_msg}\n\n（未获胜，机缘已消耗；已完成的探索结算不受影响）"
        return True, msg, {"pve_won": False}

    async def accept_legacy_challenge(self, user_id: str) -> tuple[bool, str]:
        """应邀挑战当前 pending 的传承之地（「探索秘境 传承」，含历练来源）。

        复用 challenge_legacy_guardian 既有规则（失败不致死、无奖励；平局
        视同失败——其内部 won=False 已涵盖）；胜利后按 pending 记录的
        legacy_type 建传承实例（不自动激活）。叙事文案沿用 narrative
        legacy_encounter 模板簇（design D8）。

        Returns:
            (是否获胜, 消息)。无 pending/已过期/热重载丢失 →
            (False, 机缘已消散提示)。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        entry = self.encounter_store.get_active(user_id, KIND_LEGACY)
        if entry is None:
            return (
                False,
                "🌀 当前没有可应邀的传承之地（机缘已消散；秘境/历练结算有概率触发）。",
            )
        if not (self.pve_combat_mgr and self.impart_mgr):
            # 系统未就绪属异常：保留 pending，不消耗机缘
            return False, "❌ 传承系统未就绪，请稍后再试。"

        # 应邀即消耗机缘（与旧内联路径"触发即消耗一次机会"口径一致）
        self.encounter_store.consume(user_id, KIND_LEGACY)
        won, battle_msg = await self.pve_combat_mgr.challenge_legacy_guardian(player)
        # 守护战写回了 hp（失败下限 1），需显式落库——旧内联路径靠
        # finish_exploration 末尾的统一 update_player 顺带持久化
        await self.db.update_player(player)

        if not won:
            # 失败/平局：机缘消耗，不获得传承（模板簇 encounter_lose）
            msg = render_narrative(
                self.config_manager,
                "legacy_encounter",
                "encounter_lose",
                {"battle_msg": battle_msg},
            )
            # 模板的 \n\n 前缀为结算消息内联追加设计（见 narrative 模块注释），
            # 独立回复场景去掉前导空行
            return False, msg.lstrip("\n")

        legacy_type = entry.payload.get("legacy_type", "rift")
        instance = await self.impart_mgr.create_legacy(
            player.user_id, legacy_type, activate=False
        )
        if not instance:
            return False, "❌ 传承机缘异常，请稍后再试。"
        name = self.impart_mgr.get_type_name(legacy_type)
        # 传承之地文案单源：narrative legacy_encounter 模板簇（与历练/宗门同簇）
        msg = render_narrative(
            self.config_manager,
            "legacy_encounter",
            "encounter_win",
            {"battle_msg": battle_msg, "name": name, "instance_id": instance.id},
        )
        return True, msg.lstrip("\n")

    # -------- GM 强制触发（design D4：与判定路径共用挂起逻辑，仅跳过概率） --------

    async def force_puzzle_encounter(self, user_id: str) -> tuple[bool, str]:
        """GM 强触古阵谜题遭遇：缺省上下文 rift_level=1、修为基数取秘境 1 级 exp_range。

        Returns:
            (是否成功, 含谜题题面的确认消息)——GM 需要看到题面。
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        # 缺省修为基数：秘境 1 级 exp_range（与 D6 公式衔接）；秘境 1 缺失时
        # 回落 finish_exploration 的兼容默认奖励区间
        rift_one = await self.db.ext.get_rift_by_id(1)
        if rift_one:
            exp_range = rift_one.get_rewards().get("exp", [1000, 5000])
        else:
            exp_range = [1000, 5000]
        exp_base = random.randint(int(exp_range[0]), int(exp_range[1]))
        hint = self._pend_puzzle_encounter(player, 1, exp_base)
        name = getattr(player, "user_name", "") or user_id
        return True, f"✅ 已为【{name}】触发古阵谜题遭遇：{hint}"

    async def force_beast_encounter(self, user_id: str) -> tuple[bool, str]:
        """GM 强触妖兽拦路遭遇：缺省 rift_level=1、enemy_group=None（回落全局池）。"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        self._pend_beast_encounter(player, 1, None)
        name = getattr(player, "user_name", "") or user_id
        return (
            True,
            f"✅ 已为【{name}】触发妖兽拦路遭遇（玩家发送「探索秘境 迎战」响应）",
        )

    async def force_legacy_encounter(self, user_id: str) -> tuple[bool, str]:
        """GM 强触传承之地遭遇：缺省 legacy_type="rift"（design D4/D8）。"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        self._pend_legacy_encounter(user_id, legacy_type="rift", source="rift")
        name = getattr(player, "user_name", "") or user_id
        return (
            True,
            f"✅ 已为【{name}】触发传承之地遭遇（玩家发送「探索秘境 传承」应邀）",
        )

    def _is_pill_item(self, item_name: str) -> bool:
        """检查物品是否为丹药"""
        if self.config_manager and hasattr(self.config_manager, "is_pill"):
            return self.config_manager.is_pill(item_name)
        return False

    def _get_rift_level_by_player(self, player: Player) -> int:
        """根据玩家境界确定秘境等级"""
        level_index = player.level_index
        if level_index <= 5:
            return 1  # 低级秘境
        elif level_index <= 12:
            return 2  # 中级秘境
        else:
            return 3  # 高级秘境

    async def _roll_rift_drops(
        self, player: Player, rift_level: int, item_chance: int
    ) -> list[tuple[str, int]]:
        """
        根据秘境等级随机掉落物品

        Args:
            player: 玩家对象
            rift_level: 秘境等级 (1-3)
            item_chance: 掉落概率

        Returns:
            掉落物品列表 [(物品名, 数量), ...]
        """
        dropped_items = []

        # 检查是否触发物品掉落
        if random.randint(1, 100) > item_chance:
            return dropped_items

        # 获取对应等级的掉落表
        drop_table = self.RIFT_DROP_TABLE.get(rift_level, self.RIFT_DROP_TABLE[1])

        # 加权随机选择物品（秘境保证至少掉落1件）
        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)

        current_weight = 0
        for item in drop_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_items.append((item["name"], count))
                break

        # 高级秘境有50%概率额外掉落一件
        if rift_level >= 2 and random.randint(1, 100) <= 50:
            roll = random.randint(1, total_weight)
            current_weight = 0
            for item in drop_table:
                current_weight += item["weight"]
                if roll <= current_weight:
                    count = random.randint(item["min"], item["max"])
                    dropped_items.append((item["name"], count))
                    break

        # 稀有丹药掉落检测
        pill_drops = self._roll_pill_drops(rift_level)
        if pill_drops:
            dropped_items.extend(pill_drops)

        return dropped_items

    def _roll_pill_drops(self, rift_level: int) -> list[tuple[str, int]]:
        """
        根据秘境等级随机掉落稀有丹药

        Args:
            rift_level: 秘境等级 (1-3)

        Returns:
            掉落丹药列表 [(丹药名, 数量), ...]
        """
        dropped_pills = []

        # 获取丹药掉落概率
        pill_chance = self.RIFT_PILL_DROP_CHANCE.get(rift_level, 3)

        # 检查是否触发丹药掉落
        if random.randint(1, 100) > pill_chance:
            return dropped_pills

        # 获取对应等级的丹药掉落表
        pill_table = self.RIFT_PILL_DROP_TABLE.get(
            rift_level, self.RIFT_PILL_DROP_TABLE[1]
        )

        # 加权随机选择丹药
        total_weight = sum(item["weight"] for item in pill_table)
        roll = random.randint(1, total_weight)

        current_weight = 0
        for item in pill_table:
            current_weight += item["weight"]
            if roll <= current_weight:
                count = random.randint(item["min"], item["max"])
                dropped_pills.append((item["name"], count))
                break

        return dropped_pills
