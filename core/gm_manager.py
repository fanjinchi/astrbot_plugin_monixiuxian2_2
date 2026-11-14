"""GM 管理器 - 处理修仙插件的管理员命令。"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import logger

try:
    from ..config_manager import ConfigManager
    from ..data import DataBase
    from ..models import Player
    from ..models_extended import UserStatus
except ImportError:
    # 独立运行（测试）时降级加载依赖
    import importlib.util

    def _load_module(name, rel_path):
        """Import a plugin module by file path so this file can run standalone under tests."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    # 在独立测试环境中这些类仅用于类型标注，使用 object 占位
    ConfigManager = object
    DataBase = object

    _models = _load_module("models", "models.py")
    Player = _models.Player
    _models_extended = _load_module("models_extended", "models_extended.py")
    UserStatus = _models_extended.UserStatus

try:
    from ..managers.impart_manager import LEGACY_TYPE_NAMES
except ImportError:
    # 独立测试环境降级：与 managers/impart_manager.py 保持一致的最小映射
    LEGACY_TYPE_NAMES = {
        "common": "通用传承",
        "sect": "宗门传承",
        "adventure": "历练传承",
        "rift": "秘境传承",
    }

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent

    from ..core import BusyState, EquipmentManager, StorageRingManager

try:
    from .time_skip_registry import TimeSkipRegistry
except ImportError:
    # 独立运行（测试）时降级加载
    _tsr = _load_module("time_skip_registry", "core/time_skip_registry.py")
    TimeSkipRegistry = _tsr.TimeSkipRegistry


# 日志文件大小阈值：500 MB
LOG_MAX_SIZE_BYTES = 500 * 1024 * 1024


def _is_at_component(component) -> bool:
    """通过类名判断消息段是否为 At（@）。"""
    return type(component).__name__ == "At"


class GMManager:
    """GM 命令业务管理器。"""

    def __init__(
        self,
        db: DataBase,
        config_manager: ConfigManager,
        storage_ring_manager: "StorageRingManager",
        equipment_manager: "EquipmentManager",
        adventure_manager=None,
        rift_manager=None,
        boss_manager=None,
        bounty_manager=None,
        plugin_data_path: Path = None,
        broadcast_callback=None,
        sect_manager=None,
        impart_manager=None,
        *,
        busy_state: "BusyState",
        health_service=None,
    ):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.equipment_manager = equipment_manager
        self.adventure_manager = adventure_manager
        self.rift_manager = rift_manager
        self.boss_manager = boss_manager
        self.bounty_manager = bounty_manager
        self.sect_manager = sect_manager
        self.impart_manager = impart_manager
        self.busy_state = busy_state
        # child A 健康域：气血设置与强制结算的 current_hp 边界；
        # 测试夹具可不接线，其余 GM 命令不依赖它。
        self.health_service = health_service
        self.plugin_data_path = plugin_data_path
        self.broadcast_callback = broadcast_callback

        # 时间快进覆盖清单注册表（openspec change: gm-time-skip-registry）：
        # 从各字段属主模块的 TIME_SKIP_ENTRIES 常量装配汇总（provider 列表与
        # 惰性 import 见 core/time_skip_registry.py design D3）。
        self._time_skip = TimeSkipRegistry.from_providers()

        # 子命令路由表
        self._commands = {
            "帮助": self.cmd_help,
            "设置境界": self.cmd_set_level,
            "设置修为": self.cmd_set_experience,
            "设置灵石": self.cmd_set_gold,
            "设置气血": self.cmd_set_hp,
            "设置战斗气血": self.cmd_set_battle_hp,
            "设置真元": self.cmd_set_mp,
            "设置攻击": self.cmd_set_atk,
            "设置精神力": self.cmd_set_mental_power,
            "设置贡献": self.cmd_set_sect_contribution,
            "设置职位": self.cmd_set_sect_position,
            "师承推进": self.cmd_advance_master,
            "给予装备": self.cmd_give_equipment,
            "给予物品": self.cmd_give_item,
            "卸下装备": self.cmd_unequip,
            "给予传承": self.cmd_give_legacy,
            "清除传承": self.cmd_clear_legacy,
            "清除传承状态": self.cmd_clear_legacy_state,
            "清除cd": self.cmd_clear_cd,
            "清除CD": self.cmd_clear_cd,
            "清除悬赏": self.cmd_clear_bounty,
            "触发历练结算": self.cmd_force_adventure,
            "强制历练迎战": self.cmd_force_adventure_fight,
            "触发秘境结算": self.cmd_force_rift,
            "触发秘境谜题": self.cmd_force_rift_puzzle,
            "触发秘境妖兽": self.cmd_force_rift_beast,
            "触发秘境传承": self.cmd_force_rift_legacy,
            "生成boss": self.cmd_spawn_boss,
            "生成Boss": self.cmd_spawn_boss,
            "生成BOSS": self.cmd_spawn_boss,
            # 测试工具子命令（纯中文指令无大小写别名，参照「清除cd/清除CD」
            # 先例——大小写别名仅为拉丁字母子命令存在）
            "时间快进": self.cmd_time_skip,
            "清除全部冷却": self.cmd_clear_all_cooldowns,
            "随机种子": self.cmd_seed,
        }

    # ========== 通用工具 ==========

    def _resolve_target(
        self, event: "AstrMessageEvent", args: str, single_token_is_target: bool = False
    ) -> tuple[str | None, str]:
        """解析目标玩家。

        Args:
            event: 消息事件，用于提取 @mention 与发送者。
            args: 命令剩余参数原文。
            single_token_is_target: 目标型子命令（参数不可能是纯数字数值）
                置 True，允许单个 5-12 位数字 token 直接作为目标 ID，
                例如「清除传承状态 900000002」；数值型子命令保持 False，
                单个数字仍是命令自身参数（如「设置修为 5000」）。

        Returns:
            (目标 user_id 或 None, 剩余参数字符串)；省略目标时目标为发送者。

        优先级：
        1. 消息中的 @mention
        2. 参数中的纯数字 user_id（≥2 token 时首数字 token 必为目标；
           单 token 时仅 single_token_is_target 且 5-12 位才视为目标）
        3. 省略目标时使用命令发送者
        """
        # 1. 从消息链中解析 At
        message_chain = []
        if hasattr(event, "message_obj") and event.message_obj:
            message_chain = getattr(event.message_obj, "message", []) or []

        for component in message_chain:
            if _is_at_component(component):
                candidate = None
                for attr in ("qq", "target", "uin", "user_id"):
                    candidate = getattr(component, attr, None)
                    if candidate:
                        break
                if candidate:
                    # 从参数中移除对应的 @xxx 文本，避免后续解析将其误认为命令参数
                    cleaned_args = re.sub(r"^@\S+\s*", "", args, count=1)
                    return str(candidate).lstrip("@"), cleaned_args

        # 2. 从剩余参数中取第一个 token，如果是数字则视为 user_id
        tokens = args.split() if args else []
        if len(tokens) >= 2 and tokens[0].lstrip("@").isdigit():
            target_id = tokens[0].lstrip("@")
            remaining = " ".join(tokens[1:])
            return target_id, remaining
        # 目标型子命令下，单个 5-12 位数字 token 视为目标 ID
        # （平台 user_id 通常 5 位以上；短数字保留给数值参数与传承编号）
        if (
            single_token_is_target
            and len(tokens) == 1
            and tokens[0].lstrip("@").isdigit()
            and 5 <= len(tokens[0].lstrip("@")) <= 12
        ):
            return tokens[0].lstrip("@"), ""

        # 3. 未指定目标，默认使用发送者
        sender_id = str(event.get_sender_id()) if event.get_sender_id() else None
        return sender_id, args

    async def _get_player(self, user_id: str) -> Player | None:
        """Fetch a Player by id, returning None for empty or unknown ids."""
        if not user_id:
            return None
        return await self.db.get_player_by_id(user_id)

    def _ensure_log_file(self) -> Path:
        """确保日志文件存在并返回路径。"""
        if not self.plugin_data_path:
            return Path("gm_operations.log")
        log_path = self.plugin_data_path / "gm_operations.log"
        self.plugin_data_path.mkdir(parents=True, exist_ok=True)
        return log_path

    def _rotate_log_if_needed(self, log_path: Path):
        """当日志文件超过阈值时进行轮转。"""
        if not log_path.exists():
            return
        try:
            size = log_path.stat().st_size
        except OSError:
            return
        if size >= LOG_MAX_SIZE_BYTES:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            rotated = log_path.parent / f"gm_operations_{timestamp}.log"
            try:
                os.rename(log_path, rotated)
            except OSError:
                logger.warning("【GM管理器】日志轮转失败")

    def _log_operation(
        self,
        gm_user_id: str,
        target_user_id: str | None,
        command: str,
        args: str,
        success: bool,
        message: str,
    ):
        """记录 GM 操作到日志文件。"""
        try:
            log_path = self._ensure_log_file()
            self._rotate_log_if_needed(log_path)
            entry = {
                "timestamp": int(time.time()),
                "gm_user_id": gm_user_id,
                "target_user_id": target_user_id,
                "command": command,
                "args": args.strip(),
                "success": success,
                "message": message,
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"【GM管理器】写入审计日志失败: {e}")

    def _pop_confirmation(self, args: str) -> tuple[bool, str]:
        """检查并移除参数末尾的 '确认'。"""
        tokens = args.split() if args else []
        if tokens and tokens[-1] == "确认":
            return True, " ".join(tokens[:-1])
        return False, args

    def _parse_int(self, value: str) -> int | None:
        """Parse an int from raw user input; return None when invalid."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _item_exists(self, item_name: str) -> bool:
        """检查物品是否存在于配置中（覆盖所有已配置的物品类型）。

        包含物品、武器、各类丹药、储物戒与心法配置表；
        不可入戒的类型（丹药、储物戒）由下游 store_item 拦截并给出明确提示。
        """
        cm = self.config_manager
        item_tables = (
            cm.items_data,
            cm.weapons_data,
            cm.pills_data,
            cm.exp_pills_data,
            cm.utility_pills_data,
            cm.storage_rings_data,
            cm.heart_methods_data,
        )
        return any(item_name in table for table in item_tables)

    # ========== 分发入口 ==========

    async def dispatch(
        self, gm_user_id: str, event: "AstrMessageEvent", sub_command: str, args: str
    ) -> tuple[bool, str]:
        """分发 GM 子命令。"""
        if not sub_command:
            message = "❌ 请输入 GM 子命令，例如：/修仙GM 帮助"
            self._log_operation(gm_user_id, None, "", args, False, message)
            return False, message

        handler = self._commands.get(sub_command)
        if not handler:
            available = ", ".join(sorted(set(self._commands.keys())))
            message = f"❌ 未知 GM 子命令「{sub_command}」。可用：{available}"
            target_id, _ = self._resolve_target(event, args)
            self._log_operation(
                gm_user_id, target_id, sub_command, args, False, message
            )
            return False, message

        try:
            success, message = await handler(event, args)
        except Exception as e:
            logger.error(f"【GM管理器】执行命令 {sub_command} 失败: {e}")
            success, message = False, f"❌ 执行失败：{e}"

        target_id, _ = self._resolve_target(event, args)
        self._log_operation(gm_user_id, target_id, sub_command, args, success, message)
        return success, message

    # ========== 子命令实现 ==========

    async def cmd_help(self, event: "AstrMessageEvent", args: str) -> tuple[bool, str]:
        """GM 帮助命令。"""
        # 时间快进覆盖域清单：生成自注册表（openspec change: gm-time-skip-registry），
        # 新增冷却域声明即自动列出，帮助不再手抄清单；同 label 条目去重。
        covered = "、".join(
            dict.fromkeys(label for label, _ in self._time_skip.entries())
        )
        help_text = (
            "🔧 修仙GM 指令大全\n"
            "━━━━━━━━━━━━━━━\n"
            "\n"
            "📖 角色属性\n"
            "  设置境界 [@玩家/ID] <境界名>\n"
            "  设置修为 [@玩家/ID] <数值>\n"
            "  设置灵石 [@玩家/ID] <数值>\n"
            "  设置气血 [@玩家/ID] <数值> （永久底数）\n"
            "  设置战斗气血 [@玩家/ID] <数值> （同时设底数与当前气血）\n"
            "  设置真元 [@玩家/ID] <数值> （映射为迅捷）\n"
            "  设置攻击 [@玩家/ID] <数值> （映射为伤害）\n"
            "  设置精神力 [@玩家/ID] <数值> （映射为身法）\n"
            "\n"
            "🏛 宗门\n"
            "  设置贡献 [@玩家/ID] <数值>\n"
            "  设置职位 [@玩家/ID] <职位名/0-4> （宗主/长老/亲传弟子/内门弟子/外门弟子）\n"
            "\n"
            "⛓ 师承任务\n"
            "  师承推进 [@玩家/ID] <事件> [数量] （事件：战斗/历练/突破/捐献；确定性推进）\n"
            "\n"
            "🎒 装备物品\n"
            "  给予装备 [@玩家/ID] <物品名> [数量]\n"
            "  给予物品 [@玩家/ID] <物品名> [数量]\n"
            "  卸下装备 [@玩家/ID] <槽位/名称>\n"
            "\n"
            "✨ 传承\n"
            "  给予传承 [@玩家/ID] [类型] （common/sect/adventure/rift 或中文别名，默认 common）\n"
            "  清除传承 [@玩家/ID] [编号/全部] （无编号或「全部」清除该玩家全部）\n"
            "  清除传承状态 [@玩家/ID] （清除挑战冷却与夺后保护期）\n"
            "\n"
            "⏱ 状态与结算\n"
            "  清除CD [@玩家/ID] 确认\n"
            "  清除悬赏 [@玩家/ID] 确认 （进行中悬赏+放弃冷却）\n"
            "  触发历练结算 [@玩家/ID] （不战而结；挂在战前抉择时请改用下条）\n"
            "  强制历练迎战 [@玩家/ID] （代玩家应战锁定的强敌，真实胜负入账）\n"
            "  触发秘境结算 [@玩家/ID]\n"
            "\n"
            "🌀 秘境遭遇（功能测试）\n"
            "  触发秘境谜题 [@玩家/ID] （挂起古阵谜题遭遇并回显题面）\n"
            "  触发秘境妖兽 [@玩家/ID] （挂起妖兽遭遇，玩家以「探索秘境 迎战」响应）\n"
            "  触发秘境传承 [@玩家/ID] （挂起传承之地遭遇，玩家以「探索秘境 传承」应邀）\n"
            "\n"
            "👹 系统\n"
            "  生成Boss\n"
            "\n"
            "🧪 测试工具（⚠️ 仅限测试实例）\n"
            "  时间快进 <秒> 确认 （全库到期类时间戳前移，不可逆；不唤醒睡眠中的定时任务，\n"
            "    Boss/灵眼下轮醒来即触发，需要立即生成请用「生成Boss」；前移贷款到期会真实触发逾期追杀）\n"
            f"    覆盖域：{covered}\n"
            "  清除全部冷却 [@玩家/ID] 确认 （忙碌/决斗切磋/双修/悬赏/传承/历练路线休整一键清零）\n"
            "  随机种子 <整数> / 随机种子 重置 （进程级固定全局随机序列，同进程其他插件亦受影响；\n"
            "    重置或重启进程恢复；与测试平台 deterministic+seed 同机制，后执行者生效）\n"
            "\n"
            "💡 目标玩家可省略，默认作用于发送者；\n"
            "💡 带 [] 的参数可省略，<> 为必填。"
        )
        return True, help_text

    async def cmd_give_legacy(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """给予传承实例：给予传承 [@玩家/ID] [类型]，类型默认 common（支持中文别名）。

        仅用于功能测试与数据修复：创建的实例为未激活态、传承值 0，
        sect 类型自动绑定目标玩家当前所在宗门。
        """
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        if not self.impart_manager:
            return False, "❌ 传承系统未就绪！"

        type_arg = remaining.strip() or "common"
        # 中文别名：同时接受全名（秘境传承）与短名（秘境）
        alias = {v: k for k, v in LEGACY_TYPE_NAMES.items()}
        alias.update({v.replace("传承", ""): k for k, v in LEGACY_TYPE_NAMES.items()})
        legacy_type = alias.get(type_arg, type_arg)
        if legacy_type not in LEGACY_TYPE_NAMES:
            options = "、".join(f"{v}/{k}" for k, v in LEGACY_TYPE_NAMES.items())
            return False, f"❌ 未知传承类型【{type_arg}】，可选：{options}"

        # sect 类型必须绑定目标玩家当前宗门：无宗门时拒绝（避免产生
        # 无法被 PK/回收匹配的游离宗门传承，违反 sect-system spec
        # 「宗门传承 SHALL 额外绑定所属宗门」不变式）
        if legacy_type == "sect":
            if not player.sect_id:
                return False, (
                    f"❌ 无法给予宗门传承：{player.user_name} 当前无宗门，"
                    "宗门传承需绑定所属宗门！"
                )
            sect_id = player.sect_id
        else:
            sect_id = None
        instance = await self.impart_manager.create_legacy(
            target_id, legacy_type, sect_id=sect_id, activate=False
        )
        if not instance:
            return False, "❌ 传承实例创建失败，请查看日志！"
        name = self.impart_manager.get_type_name(legacy_type)
        return True, (
            f"✅ 已为 {player.user_name} 创建【{name}】传承 #{instance.id}\n"
            f"（未激活，传承值 0；发送「激活传承 {instance.id}」开始累积）"
        )

    async def cmd_clear_legacy(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """清除传承：清除传承 [@玩家/ID] [编号]，无编号时删除该玩家全部传承实例。"""
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        # 单裸数字歧义：当该数字命中发送者自己持有的传承编号时，按「清除自己的传承 #N」
        # 处理——实例 ID 增至 5 位后会与用户 ID 位数重叠，管理员裸输编号更可能是
        # 清自己的传承，而不是把数字当成目标玩家 ID（后者可用 @ 或双 token 明确指定）
        raw = args.strip()
        if not remaining and " " not in raw and raw.lstrip("#").isdigit():
            own = await self.db.ext.list_legacy_instances_by_owner(
                str(event.get_sender_id())
            )
            if any(i.id == int(raw.lstrip("#")) for i in own):
                target_id = str(event.get_sender_id())
                remaining = raw.lstrip("#")
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        if not self.impart_manager:
            return False, "❌ 传承系统未就绪！"

        instances = await self.db.ext.list_legacy_instances_by_owner(target_id)
        if not instances:
            return False, f"❌ {player.user_name} 未持有任何传承！"

        arg = remaining.strip().lstrip("#")
        if arg and arg != "全部":
            if not arg.isdigit():
                return (
                    False,
                    "❌ 编号须为数字或「全部」，例如：/修仙GM 清除传承 900000002 3",
                )
            iid = int(arg)
            if not any(i.id == iid for i in instances):
                return False, f"❌ {player.user_name} 未持有编号 {iid} 的传承！"
            await self.db.ext.delete_legacy_instance(iid)
            return True, f"✅ 已删除 {player.user_name} 的传承 #{iid}"

        for inst in instances:
            await self.db.ext.delete_legacy_instance(inst.id)
        return (
            True,
            f"✅ 已删除 {player.user_name} 的全部传承（共 {len(instances)} 条）",
        )

    async def cmd_clear_legacy_state(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """清除传承状态：清除挑战冷却与被夺保护期，用于测试重入与数据修复。

        同时清掉该玩家作为挑战者的全部冷却记录（对不同目标的），
        以及作为被夺者的保护期。注意：不删除传承实例本身。
        """
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        if not self.impart_manager:
            return False, "❌ 传承系统未就绪！"

        # 两段删除同属一次清除动作，必须同生共死：各自提交时第二段失败会留下
        # 「挑战冷却已清、保护期未清」的半提交状态（S9 同族残留）。CM 单事务；
        # 两叶子已按 D2 门控，块内不自提交
        async with self.db.transaction():
            cooldown_deleted = await self.db.ext.delete_impart_pk_cooldowns(target_id)
            protection_deleted = await self.db.ext.delete_impart_snatch_protection(
                target_id
            )
        return True, (
            f"✅ 已清除 {player.user_name} 的传承状态："
            f"挑战冷却 {cooldown_deleted} 条、保护期 {protection_deleted} 条"
        )

    async def cmd_set_level(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """设置境界。"""
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        realm_name = remaining.strip()
        if not realm_name:
            return False, "❌ 请输入境界名称，例如：/修仙GM 设置境界 筑基一阶"

        found_index = self.config_manager.get_level_index_by_name(
            realm_name, player.cultivation_type
        )

        if found_index is None:
            valid_names = [
                self.config_manager.get_level_name(level, player.cultivation_type)
                for level in range(
                    1, self.config_manager.get_max_level(player.cultivation_type) + 1
                )
            ]
            return False, (
                f"❌ 未找到境界「{realm_name}」。\n"
                f"可用境界：{', '.join(valid_names[:20])}{'...' if len(valid_names) > 20 else ''}"
            )

        player.level_index = found_index
        await self.db.update_player(player)
        return (
            True,
            f"✅ 已将【{player.user_name or target_id}】的境界设置为「{realm_name}」",
        )

    async def cmd_set_sect_contribution(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's sect contribution value."""
        target_id, remaining = self._resolve_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        value = self._parse_int(remaining.strip())
        if value is None or value < 0:
            return False, "❌ 请输入非负整数，例如：/修仙GM 设置贡献 900000002 30000"

        player.sect_contribution = value
        await self.db.update_player(player)
        return (
            True,
            f"✅ 已将【{player.user_name or target_id}】的宗门贡献设置为 {value:,}",
        )

    async def cmd_set_sect_position(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's sect position (0-4 or name)."""
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        if not self.sect_manager:
            return False, "❌ 宗门管理器未初始化！"

        token = remaining.strip()
        position_names = {self.sect_manager.get_position_name(i): i for i in range(5)}
        if token.isdigit():
            position = int(token)
        else:
            position = position_names.get(token)
        if position is None or position < 0 or position > 4:
            return False, (
                "❌ 无效的职位！可用：0-4 或 宗主/长老/亲传弟子/内门弟子/外门弟子"
            )

        player.sect_position = position
        await self.db.update_player(player)
        pos_name = self.sect_manager.get_position_name(position)
        return (
            True,
            f"✅ 已将【{player.user_name or target_id}】的职位设置为「{pos_name}」",
        )

    async def cmd_advance_master(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: deterministically advance the target's master task chain.

        Event tokens: 战斗(win_pve) / 历练(adventure_complete) / 突破(breakthrough)
        / 捐献(donate, optional amount in stones). PvE win-pve counting is
        probabilistic in normal flow (see pve combat encounter rates), so this
        command provides a deterministic path for tests.
        """
        tokens = args.split() if args else []
        if tokens and tokens[0].lstrip("@").isdigit():
            target_id = tokens[0].lstrip("@")
            rest = tokens[1:]
        else:
            target_id, remaining = self._resolve_target(event, args)
            rest = remaining.split() if remaining else []

        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"
        if not self.sect_manager:
            return False, "❌ 宗门管理器未初始化！"

        if not rest:
            return (
                False,
                "❌ 请输入事件：战斗/历练/突破/捐献，例如：/修仙GM 师承推进 900000002 战斗",
            )
        event_map = {
            "战斗": "win_pve",
            "历练": "adventure_complete",
            "突破": "breakthrough",
            "捐献": "donate",
        }
        event_type = event_map.get(rest[0])
        if not event_type:
            return False, f"❌ 未知事件「{rest[0]}」。可用：战斗/历练/突破/捐献"

        amount = 1
        if len(rest) > 1:
            parsed = self._parse_int(rest[1])
            if parsed is not None and parsed > 0:
                amount = parsed

        try:
            master_msg = await self.sect_manager.advance_master_progress(
                target_id, event_type, amount
            )
        except Exception as e:
            logger.warning("【修仙插件】师承推进失败", exc_info=True)
            return False, f"❌ 师承推进失败：{e}"

        if master_msg:
            # 片段自带 📜/⚠️ 内容符号与「师承任务」语境，直接裸渲染，
            # 避免与包装头冲突（如发放失败时出现 "✅ 已推进…\n\n⚠️ 发放失败"）
            return True, master_msg.strip()
        return (
            True,
            "✅ 已推进师承任务：当前阶段与该事件不匹配（查看 /师承任务 了解阶段）。",
        )

    async def _set_numeric_attr(
        self,
        event: "AstrMessageEvent",
        args: str,
        attr_name: str,
        field_name: str,
        display_name: str,
    ) -> tuple[bool, str]:
        """设置数值属性。"""
        target_id, remaining = self._resolve_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        value = self._parse_int(remaining.strip())
        if value is None:
            return (
                False,
                f"❌ 请输入有效的{display_name}数值，例如：/修仙GM 设置{display_name} 1000",
            )

        setattr(player, field_name, value)
        await self.db.update_player(player)
        return (
            True,
            f"✅ 已将【{player.user_name or target_id}】的{display_name}设置为 {value:,}",
        )

    async def cmd_set_experience(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's experience."""
        return await self._set_numeric_attr(event, args, "修为", "experience", "修为")

    async def cmd_set_gold(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's gold (spirit stones)."""
        return await self._set_numeric_attr(event, args, "灵石", "gold", "灵石")

    async def cmd_set_hp(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's permanent base HP.

        三层语义（child A design）：「设置气血」改的是永久底数 base_hp，
        气血上限由它在运行时聚合得出；战斗/恢复层 current_hp 不动，若新
        上限低于当前气血则就地收敛（下一次权威读取同样会收敛）。
        """
        ok, msg = await self._set_numeric_attr(event, args, "气血", "base_hp", "气血")
        if ok and self.health_service is not None:
            target_id, _ = self._resolve_target(event, args)
            player = await self._get_player(target_id)
            if player:
                await self.health_service.clamp_current_hp(player)
        return ok, msg

    async def cmd_set_battle_hp(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: set the target player's battle HP (ceiling and current).

        「设置气血」只改永久底数 base_hp（三层语义，current_hp 由战斗/恢复层
        管辖）；本命令在抬高底数的同时把当前气血一并设到同一数值，用于构造
        长局（PVP 效果用例靠 8000 血局触发低频效果）。当前气血一律走
        HealthService.set_current_hp 权威写入（自带 settle + clamp），未接线
        HealthService 的独立测试装配退化为直写。
        """
        ok, msg = await self._set_numeric_attr(event, args, "气血", "base_hp", "气血")
        if not ok:
            return ok, msg

        target_id, remaining = self._resolve_target(event, args)
        value = self._parse_int(remaining.strip())
        player = await self._get_player(target_id)
        if value is None or player is None:
            return ok, msg

        if self.health_service is not None:
            current = await self.health_service.set_current_hp(player, value)
            max_hp = self.health_service.compute_max_hp(player)
        else:
            # 无 HealthService 时退化为直写：base_hp 已在上一行设成同一值，
            # 动态上限不低于它，故目标值必在界内。
            player.current_hp = value
            await self.db.update_player(player)
            current, max_hp = value, None

        # 回执只报「底数 + 当前气血」这两个真的被设成 value 的量：max_hp 是
        # 运行时聚合（base_hp + 装备/功法/丹药加成），带装配的玩家必然高于
        # value，把 value 说成上限会让 GM 误判真实血量（评审 P2-1）。
        msg = f"✅ 已将【{player.user_name or target_id}】的气血底数与当前气血设置为 {value:,}"
        if max_hp is not None and max_hp != value:
            msg += f"（当前上限 {max_hp:,}，含装备/功法加成）"
        if current != value:
            msg += f"（实际当前气血 {current:,}）"
        return True, msg

    async def cmd_set_mp(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: legacy 真元 alias, mapped to speed after the attribute rework."""
        # 真元字段已废弃，映射到迅捷以保持 GM 工具可用。
        return await self._set_numeric_attr(event, args, "真元", "speed", "真元")

    async def cmd_set_atk(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: legacy 攻击 alias, mapped to damage after the attribute rework."""
        # 攻击字段已废弃，映射到伤害。
        return await self._set_numeric_attr(event, args, "攻击", "damage", "攻击")

    async def cmd_set_mental_power(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: legacy 精神力 alias, mapped to agility after the attribute rework."""
        # 精神力字段已废弃，映射到身法。
        return await self._set_numeric_attr(event, args, "精神力", "agility", "精神力")

    async def cmd_give_equipment(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: give an equipment item into the target player's storage ring."""
        return await self._give_item(event, args, "装备")

    async def cmd_give_item(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """GM command: give a consumable item into the target player's storage ring."""
        return await self._give_item(event, args, "物品")

    async def _give_item(
        self, event: "AstrMessageEvent", args: str, item_kind: str
    ) -> tuple[bool, str]:
        """给予物品或装备（进储物戒）。"""
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        tokens = remaining.split() if remaining else []
        if not tokens:
            return (
                False,
                f"❌ 请输入{item_kind}名称，例如：/修仙GM 给予{item_kind} 青铜剑",
            )

        item_name = tokens[0]
        count = 1
        if len(tokens) > 1:
            parsed = self._parse_int(tokens[1])
            if parsed is not None and parsed > 0:
                count = parsed

        if not self._item_exists(item_name):
            return False, f"❌ 物品「{item_name}」不存在于配置中！"

        success, msg = await self.storage_ring_manager.store_item(
            player, item_name, count, silent=True
        )
        if not success:
            return False, f"❌ 给予{item_kind}失败：{msg}"

        return (
            True,
            f"✅ 已向【{player.user_name or target_id}】的储物戒放入 {item_name} x{count}",
        )

    async def cmd_unequip(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """卸下装备。"""
        target_id, remaining = self._resolve_target(
            event, args, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        slot_or_name = remaining.strip()
        if not slot_or_name:
            return False, "❌ 请输入槽位或名称，例如：/修仙GM 卸下装备 武器"

        # 记录卸下前的物品名，以便后续存入储物戒
        unequipped_item_name = ""
        normalized_slot = slot_or_name.lower()
        if normalized_slot in ["武器", "weapon"]:
            unequipped_item_name = player.weapon
        elif normalized_slot in ["防具", "armor"]:
            unequipped_item_name = player.armor
        elif normalized_slot in ["主修心法", "心法", "main_technique"]:
            unequipped_item_name = player.main_technique
        else:
            techniques_list = player.get_techniques_list()
            if slot_or_name in techniques_list:
                unequipped_item_name = slot_or_name

        success, msg = await self.equipment_manager.unequip_item(player, slot_or_name)
        if not success:
            return False, f"❌ 卸下失败：{msg.removeprefix('❌ ')}"

        # 将卸下的装备存入储物戒
        store_msg = ""
        if unequipped_item_name:
            store_ok, store_msg_inner = await self.storage_ring_manager.store_item(
                player, unequipped_item_name, 1, silent=True
            )
            if store_ok:
                store_msg = f"\n{unequipped_item_name} 已自动存入储物戒"
            else:
                store_msg = (
                    f"\n⚠️ {unequipped_item_name} 存入储物戒失败：{store_msg_inner}"
                )

        return (
            True,
            f"✅ 已卸下【{player.user_name or target_id}】的 {slot_or_name}：{msg.removeprefix('✅ ')}{store_msg}",
        )

    async def cmd_clear_cd(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """清除玩家忙碌状态。"""
        confirmed, remaining = self._pop_confirmation(args)
        if not confirmed:
            return (
                False,
                "⚠️ 清除CD 为破坏性操作，请在命令末尾追加「确认」以执行。\n"
                "例如：/修仙GM 清除CD @玩家 确认",
            )

        # 清除CD 在确认后通常只剩一个目标ID（或@），优先识别纯数字ID
        remaining_tokens = remaining.split() if remaining else []
        if len(remaining_tokens) == 1 and remaining_tokens[0].isdigit():
            target_id = remaining_tokens[0]
        else:
            target_id, _ = self._resolve_target(event, remaining)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(target_id)
        if not user_cd or user_cd.type == UserStatus.IDLE:
            return False, "❌ 目标玩家当前不在任何忙碌状态！"

        # 统一走 owner 清除入口（user_cd 复位 + 镜像同步）：与 player 落库包在
        # 同一外层事务（tasks 2.1 机制定案）——R2 双写单事务，两段提交变原子
        async with self.db.transaction():
            await self.busy_state.clear(player)
            await self.db.update_player(player)

        return True, f"✅ 已清除【{player.user_name or target_id}】的忙碌状态"

    async def cmd_clear_bounty(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """清除玩家悬赏状态：进行中悬赏记录（不结算奖励）+ 放弃冷却键。

        供功能测试与运营清理悬赏状态；「清除CD」只清 user_cd 忙碌状态，
        不覆盖悬赏存储（bounty_tasks 表与 system_config.bounty_abandon_cd_<uid>）。
        冷却通过写入过期时间戳 "0" 失效（db 层无 delete_system_config）。
        """
        confirmed, remaining = self._pop_confirmation(args)
        if not confirmed:
            return (
                False,
                "⚠️ 清除悬赏 为破坏性操作，请在命令末尾追加「确认」以执行。\n"
                "例如：/修仙GM 清除悬赏 @玩家 确认",
            )

        # 确认后通常只剩一个目标ID（或@），优先识别纯数字ID
        remaining_tokens = remaining.split() if remaining else []
        if len(remaining_tokens) == 1 and remaining_tokens[0].isdigit():
            target_id = remaining_tokens[0]
        else:
            target_id, _ = self._resolve_target(event, remaining)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        # 校验读（GM 命令单条指令触发、幂等可重跑）留在 CM 外：无可清状态时
        # 不进事务、零写入（早退语义逐字不变）
        active = await self.db.ext.get_active_bounty(target_id)
        cd_key = f"bounty_abandon_cd_{target_id}"
        cd_existing = await self.db.ext.get_system_config(cd_key)
        if not active and not cd_existing:
            return (
                False,
                f"❌ 【{player.user_name or target_id}】没有可清除的悬赏状态！",
            )

        # 悬赏取消与放弃冷却键失效必须同生共死：两段各自提交时，第二段失败会留下
        # 「悬赏已取消、冷却仍生效」的半提交状态（S9 同族残留）——命令报失败却已
        # 生效，重跑也补不回被取消的悬赏。CM 单事务；两叶子已按 D2 门控（块内不提交）
        cleared = []
        async with self.db.transaction():
            if active:
                await self.db.ext.cancel_bounty(target_id)
                cleared.append(f"进行中悬赏【{active['bounty_name']}】")
            if cd_existing:
                await self.db.ext.set_system_config(cd_key, "0")
                cleared.append("放弃冷却")

        return (
            True,
            f"✅ 已清除【{player.user_name or target_id}】的{'、'.join(cleared)}",
        )

    def _resolve_force_target(self, event: "AstrMessageEvent", args: str) -> str | None:
        """Resolve the target id of a force-settle subcommand (a lone number is the id).

        通用 ``_resolve_target`` 只在 ≥2 token 时才把首个数字当目标 ID，而强制结算
        类子命令的参数只可能是目标（``触发历练结算 900000002`` 只有一个 token），
        因此这里额外放行单个数字 token。
        """
        tokens = args.split() if args else []
        if tokens and tokens[0].lstrip("@").isdigit():
            return tokens[0].lstrip("@")
        target_id, _ = self._resolve_target(event, args)
        return target_id

    async def _advance_adventure_progress(
        self, player: Player, target_id: str, reward_data: dict | None
    ) -> str:
        """Advance cross-system progress (悬赏 + 师承链) after a 历练 settlement.

        与 ``main.py`` 的同名方法同口径（玩家指令与 GM 代结算共用一份进度语义）；
        ``reward_data`` 为 ``None`` 表示本次没有新事实（重放），什么都不推进。
        师承链两处调用各自独立吞异常：进度反馈失败不该让结算结果消失。

        Args:
            player: 目标玩家对象（悬赏进度需要）。
            target_id: 目标玩家 id。
            reward_data: manager 返回的结算数据。

        Returns:
            待拼接到结算文案末尾的进度文本（可能为空串）。
        """
        # 与 main.py 同名方法逐字同口径：重放（reward_data 为空）没有新事实，
        # 悬赏与师承一起不推进——否则 GM 与玩家指令并发、GM 的 CAS 落败走重放
        # 时，会把师承「历练完成」阶段推两次（PRD AC5）。
        if not reward_data:
            return ""

        parts: list[str] = []

        if self.bounty_manager:
            bounty_tag = reward_data.get("bounty_tag", "adventure")
            bounty_value = reward_data.get("bounty_progress", 1)
            has_progress, bounty_msg = await self.bounty_manager.add_bounty_progress(
                player, bounty_tag, bounty_value
            )
            if has_progress:
                parts.append(bounty_msg)

        # 历练完成与 PvE 胜利各自独立推进，任一失败不影响另一条反馈。
        try:
            master_msg = await self.sect_manager.advance_master_progress(
                target_id, "adventure_complete"
            )
        except Exception:
            logger.warning(
                "【修仙插件】师承任务进度推进失败（强制历练完成）", exc_info=True
            )
            master_msg = None
        if master_msg:
            parts.append(master_msg)

        if (reward_data or {}).get("pve_won"):
            try:
                win_msg = await self.sect_manager.advance_master_progress(
                    target_id, "win_pve"
                )
            except Exception:
                logger.warning(
                    "【修仙插件】师承任务进度推进失败（强制历练PvE胜利）", exc_info=True
                )
                win_msg = None
            if win_msg:
                parts.append(win_msg)

        return "".join(parts)

    async def cmd_force_adventure(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制历练结算——不战而结；挂在战前抉择的单子必须走「强制历练迎战」。"""
        target_id = self._resolve_force_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(target_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 目标玩家当前不在历练中！"

        if not self.adventure_manager:
            return False, "❌ 历练管理器未初始化！"

        # 战前抉择是玩家本人的选择，GM 不能替玩家「不战而结」：早期版本在这里
        # 照样 bump 时间并报告 ✅，实际 finish_adventure 只回了一张抉择面板
        # （reward_data=None），玩家仍被锁着——假成功。2026-10-12 拍板改为诚实
        # 拒绝，代打另走「强制历练迎战」子命令。
        if await self.adventure_manager.awaits_combat_choice(target_id):
            return False, (
                "❌ 该历练已锁定强敌，正等待战前抉择，无法不战而结！\n"
                "💡 代玩家应战请发送「强制历练迎战 "
                f"{target_id}」，或由玩家本人发送「迎战」/「逃跑」。"
            )

        # 将计划完成时间提前到当前时间，立即结算
        # force-settle 例外（design §D3）：仅上移 scheduled_time，走窄写直连
        # update_user_cd_fields——BusyState 的断言/镜像语义不适用于 GM 强制结算。
        # 用窄写而不是 update_user_cd 整行回写：陈旧快照晚一步落地会把玩家已经
        # 收尾的忙碌复活成原状态（busy 只看 type，复活后重启不自愈）。窄写由
        # 共享 leaf_write 按任务所有权串行并在最外层提交。child A AC4：本入口仍是权威的 user_cd 写点——
        # 同一事务内先结算旧状态并前移恢复锚点。
        async with self.db.transaction():
            if self.health_service is not None:
                await self.health_service.settle(target_id)
            await self.db.ext.update_user_cd_fields(
                target_id, scheduled_time=int(time.time())
            )

        success, msg, reward_data = await self.adventure_manager.finish_adventure(
            target_id
        )
        if not success:
            # manager 失败消息自带 ❌（如路线配置缺失），嵌入包装头前先去重，避免 "❌ ❌"
            return False, f"❌ 历练结算失败：{msg.removeprefix('❌ ')}"

        # 兜底：上面查过之后再被玩家自己的「迎战」插进来也可能挂住抉择，
        # 此时同样不能报成功（终态判定以结算单为权威）。
        if await self.adventure_manager.awaits_combat_choice(target_id):
            return False, (
                "❌ 历练已推进到战前抉择，未能不战而结！\n"
                "💡 代玩家应战请发送「强制历练迎战 "
                f"{target_id}」，或由玩家本人发送「迎战」/「逃跑」。"
            )

        # 强制结算即"立即完成"：同时清除该玩家的历练休整窗口，
        # 允许测试脚本连续开启历练（正常流程仍按配置休整）。休整已落库（v39），
        # 清理走 manager 的 CAS 入口，GM 层不直接持有仓储。
        # 必须包 CM：clear_fatigue 是「读疲劳行 + 一条 CAS UPDATE」两次写，
        # 裸叶子写在并发下可能撞上别处的 BEGIN IMMEDIATE（design §2.4-1）。
        async with self.db.transaction():
            await self.adventure_manager.clear_fatigue(target_id)

        msg += await self._advance_adventure_progress(player, target_id, reward_data)

        return True, f"✅ 已强制结算【{player.user_name or target_id}】的历练\n{msg}"

    async def cmd_force_adventure_fight(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """Force the locked enemy to be fought on the target's behalf (test tool).

        代玩家做「迎战」选择：用 snapshot 里锁定的那只敌人真打一场，胜则
        ``resolved_win``、败则按败场规则落 ``resolved_loss``（气血 1% 地板 +
        额外休整），随后清掉休整窗口让测试脚本能继续跑。败场事实保留——
        GM 只抹冷却，不抹账本（2026-10-12 拍板）。

        Args:
            event: 消息事件（解析 @mention 与发送者）。
            args: 子命令参数，目标 ID 可省略。

        Returns:
            (是否成功, 面向 GM 的完整中文文案)。
        """
        target_id = self._resolve_force_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        if not self.adventure_manager:
            return False, "❌ 历练管理器未初始化！"

        if not await self.adventure_manager.awaits_combat_choice(target_id):
            return False, (
                "❌ 目标玩家当前没有等待应战的历练遭遇！\n"
                "💡 未遇敌的历练用「触发历练结算」，正常流程让玩家发送「迎战」。"
            )

        (
            success,
            msg,
            reward_data,
        ) = await self.adventure_manager.resolve_adventure_choice(target_id, flee=False)
        if not success:
            return False, f"❌ 强制迎战失败：{msg.removeprefix('❌ ')}"

        async with self.db.transaction():
            await self.adventure_manager.clear_fatigue(target_id)

        msg += await self._advance_adventure_progress(player, target_id, reward_data)

        return True, f"✅ 已代【{player.user_name or target_id}】应战并结算历练\n{msg}"

    async def cmd_force_rift(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制秘境结算。"""
        # 强制结算类命令的参数即目标 ID（单个数字也视为目标，见
        # _resolve_force_target）。
        target_id = self._resolve_force_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(target_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 目标玩家当前不在秘境探索中！"

        if not self.rift_manager:
            return False, "❌ 秘境管理器未初始化！"

        # 将计划完成时间提前到当前时间，立即结算
        # force-settle 例外（design §D3）：仅上移 scheduled_time，走窄写直连
        # update_user_cd_fields——BusyState 的断言/镜像语义不适用于 GM 强制结算。
        # 用窄写而不是 update_user_cd 整行回写：陈旧快照晚一步落地会把玩家已经
        # 收尾的忙碌复活成原状态（busy 只看 type，复活后重启不自愈）。窄写由
        # 共享 leaf_write 按任务所有权串行并在最外层提交。child A AC4：本入口仍是权威的 user_cd 写点——
        # 同一事务内先结算旧状态并前移恢复锚点。
        async with self.db.transaction():
            if self.health_service is not None:
                await self.health_service.settle(target_id)
            await self.db.ext.update_user_cd_fields(
                target_id, scheduled_time=int(time.time())
            )

        success, msg, reward_data = await self.rift_manager.finish_exploration(
            target_id
        )
        if not success:
            return False, f"❌ 秘境结算失败：{msg.removeprefix('❌ ')}"

        # 更新悬赏进度（与正常 /完成探索 保持一致）
        if reward_data and self.bounty_manager:
            has_progress, bounty_msg = await self.bounty_manager.add_bounty_progress(
                player, "rift", 1
            )
            if has_progress:
                msg += bounty_msg

        # 师承任务链：PvE 胜利计数（与 main.py handle_rift_complete 保持一致）
        if (reward_data or {}).get("pve_won"):
            try:
                master_msg = await self.sect_manager.advance_master_progress(
                    target_id, "win_pve"
                )
                if master_msg:
                    msg += master_msg
            except Exception:
                logger.warning(
                    "【修仙插件】师承任务PvE胜场推进失败（强制秘境结算）", exc_info=True
                )

        return (
            True,
            f"✅ 已强制结算【{player.user_name or target_id}】的秘境探索\n{msg}",
        )

    async def cmd_force_rift_puzzle(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """Force-pend a puzzle encounter for the target (add-rift-encounters task 4.1).

        Target resolution uses single_token_is_target=True (cmd_give_legacy
        precedent, design D4) so that a bare numeric token like
        「触发秘境谜题 900000002」 targets that player instead of falling back
        to the sender as a numeric command argument. The puzzle question text
        is echoed back to the GM by the manager's return message.
        """
        if not self.rift_manager:
            return False, "❌ 秘境管理器未初始化！"
        target_id, _ = self._resolve_target(event, args, single_token_is_target=True)
        return await self.rift_manager.force_puzzle_encounter(target_id)

    async def cmd_force_rift_beast(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """Force-pend a beast encounter for the target (add-rift-encounters task 4.1).

        Uses single_token_is_target=True for the same reason as
        cmd_force_rift_puzzle. Default context (rift_level=1, global enemy
        pool) is defined by the manager (design D4).
        """
        if not self.rift_manager:
            return False, "❌ 秘境管理器未初始化！"
        target_id, _ = self._resolve_target(event, args, single_token_is_target=True)
        return await self.rift_manager.force_beast_encounter(target_id)

    async def cmd_force_rift_legacy(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """Force-pend a legacy-site encounter for the target (add-rift-encounters task 4.1).

        Uses single_token_is_target=True for the same reason as
        cmd_force_rift_puzzle. The pended encounter carries legacy_type
        "rift" (design D4/D8).
        """
        if not self.rift_manager:
            return False, "❌ 秘境管理器未初始化！"
        target_id, _ = self._resolve_target(event, args, single_token_is_target=True)
        return await self.rift_manager.force_legacy_encounter(target_id)

    async def cmd_spawn_boss(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """生成世界 Boss。"""
        if not self.boss_manager:
            return False, "❌ Boss管理器未初始化！"

        success, msg, boss = await self.boss_manager.auto_spawn_boss()
        if not success:
            return False, f"❌ 生成Boss失败：{msg.removeprefix('❌ ')}"

        if self.broadcast_callback:
            try:
                await self.broadcast_callback(boss)
            except Exception as e:
                logger.warning(f"【GM管理器】广播Boss生成消息失败: {e}")

        return True, f"✅ 已生成世界Boss：{boss.boss_name}"

    # ========== 测试工具子命令（仅限测试实例，见 design D1/D4/D5/D6） ==========

    async def cmd_time_skip(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """时间快进：将注册表覆盖清单内的到期判定时间戳统一前移 N 秒。

        直接改写数据库字段（与 cmd_force_adventure 改 scheduled_time 同一先例），
        让业务逻辑在「时间已到」的真实状态下运行——不是绕过结算逻辑。
        不承诺唤醒 asyncio.sleep 中的定时任务（Boss/灵眼循环下次醒来读到
        已前移的刷新时间即触发）。前移不可逆，故沿用「确认」约定。
        覆盖清单来自 time_skip_registry 注册表（openspec change:
        gm-time-skip-registry），同一 label 的多条条目按聚合计数。回复明细
        10 行（label 聚合）vs 共前移 11 条（Boss/灵眼为两条单键行）是有意
        设计：前者是面向玩家的域粒度可读行，后者是实际行数。
        """
        confirmed, remaining = self._pop_confirmation(args)
        if not confirmed:
            return (
                False,
                "⚠️ 时间快进 为破坏性操作（全库时间戳前移、不可逆），"
                "请在命令末尾追加「确认」以执行。\n"
                "例如：/修仙GM 时间快进 3600 确认",
            )

        seconds = self._parse_int(remaining.strip())
        if seconds is None or seconds <= 0:
            return (
                False,
                "❌ 秒数须为正整数，例如：/修仙GM 时间快进 3600 确认",
            )

        # 多表改写包在一个事务里，避免快进一半留下混合时间态
        # （CM 单事务：正常退出整体提交，任何失败整体回滚——全有或全无）
        merged: dict[str, int] = {}
        order: list[str] = []
        async with self.db.transaction():
            for label, sql in self._time_skip.entries():
                params = (seconds,) * sql.count("?")
                async with self.db.conn.execute(sql, params) as cursor:
                    if label not in merged:
                        order.append(label)
                    merged[label] = merged.get(label, 0) + max(cursor.rowcount, 0)

        detail = "\n".join(f"  {label}：{merged[label]} 条" for label in order)
        total = sum(merged.values())
        return True, (
            f"✅ 时间已快进 {seconds} 秒（共前移 {total} 条记录）：\n"
            f"{detail}\n"
            "⚠️ 仅限测试实例：前移不可逆；睡眠中的定时任务（Boss/灵眼）不会被唤醒，"
            "将在下次醒来时立即触发，需要立即生成请用「生成Boss」。"
        )

    async def cmd_clear_all_cooldowns(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """清除全部冷却：一键归零目标玩家全部冷却与忙碌状态（design D3）。

        编排者：每域都走与既有子命令相同的清除路径（「清除CD」「清除悬赏」
        「清除传承状态」的并集超集），保证「GM 清除后状态 == 正常到期后状态」，
        避免第三套清除逻辑漂移。供测试用例首尾清洗状态。
        每步清除都以"存在才写"为条件，无可清除状态时零副作用。
        """
        confirmed, remaining = self._pop_confirmation(args)
        if not confirmed:
            return (
                False,
                "⚠️ 清除全部冷却 为破坏性操作，请在命令末尾追加「确认」以执行。\n"
                "例如：/修仙GM 清除全部冷却 @玩家 确认",
            )

        target_id, _ = self._resolve_target(
            event, remaining, single_token_is_target=True
        )
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        cleared: list[str] = []

        # 步骤 1-5 涉及多表改写（user_cd/players/combat_cooldowns/dual_cultivation/
        # bounty_tasks/system_config/impart_*），必须同生共死：中途失败会留下「清了一半」
        # 的混合状态。CM 单事务——正常退出整体提交，任何失败整体回滚（全有或全无）
        async with self.db.transaction():
            # 1. 忙碌状态（同「清除CD」）：统一走 owner 清除入口，保持双层同步复位
            user_cd = await self.db.ext.get_user_cd(target_id)
            if (user_cd and user_cd.type != UserStatus.IDLE) or player.state != "空闲":
                await self.busy_state.clear(player)
                await self.db.update_player(player)
                cleared.append("忙碌状态：1 条")

            # 2. 决斗/切磋冷却清零（无 ext 方法，与 combat_handlers 一样直连 conn）
            async with self.db.conn.execute(
                "UPDATE combat_cooldowns SET last_duel_time = 0, last_spar_time = 0 "
                "WHERE user_id = ? AND (last_duel_time > 0 OR last_spar_time > 0)",
                (target_id,),
            ) as cursor:
                combat_cleared = cursor.rowcount
            if combat_cleared:
                cleared.append(f"决斗/切磋冷却：{combat_cleared} 条")

            # 3. 双修冷却清零
            async with self.db.conn.execute(
                "UPDATE dual_cultivation SET last_dual_time = 0 "
                "WHERE user_id = ? AND last_dual_time > 0",
                (target_id,),
            ) as cursor:
                dual_cleared = cursor.rowcount
            if dual_cleared:
                cleared.append(f"双修冷却：{dual_cleared} 条")

            # 4. 悬赏（同「清除悬赏」）：进行中悬赏移除 + 放弃冷却键置 "0"
            # （db 层无 delete_system_config，过期时间戳写 "0" 即失效）
            active = await self.db.ext.get_active_bounty(target_id)
            if active:
                await self.db.ext.cancel_bounty(target_id)
                cleared.append(f"进行中悬赏：1 条（{active['bounty_name']}）")
            cd_key = f"bounty_abandon_cd_{target_id}"
            if await self.db.ext.get_system_config(cd_key):
                await self.db.ext.set_system_config(cd_key, "0")
                cleared.append("悬赏放弃冷却：1 条")

            # 5. 传承（同「清除传承状态」）：挑战冷却 + 被夺保护期，不删除传承实例
            pk_deleted = await self.db.ext.delete_impart_pk_cooldowns(target_id)
            if pk_deleted:
                cleared.append(f"传承挑战冷却：{pk_deleted} 条")
            protection_deleted = await self.db.ext.delete_impart_snatch_protection(
                target_id
            )
            if protection_deleted:
                cleared.append(f"传承被夺保护期：{protection_deleted} 条")

            # 6. 历练休整窗口（v39 起落库 adventure_fatigue，不再是内存字典）：
            # 放进同一事务，回滚时休整原样保留，不会出现「库回滚了、冷却清掉了」
            # 这种可重复刷历练的混合状态
            if self.adventure_manager and await self.adventure_manager.clear_fatigue(
                target_id
            ):
                cleared.append("历练休整冷却：1 条")
        # 块内原裸 conn.commit() 随 CM 转换删除（owner 层统一提交）

        if not cleared:
            return (
                False,
                f"❌ 【{player.user_name or target_id}】没有可清除的冷却状态！",
            )
        detail = "\n".join(f"  {line}" for line in cleared)
        return True, (
            f"✅ 已清除【{player.user_name or target_id}】的全部冷却状态：\n{detail}"
        )

    async def cmd_seed(self, event: "AstrMessageEvent", args: str) -> tuple[bool, str]:
        """随机种子：为当前进程注入固定全局随机种子（design D4/D5）。

        非破坏性（不改数据、可重置、进程重启自愈），不要求「确认」；
        种子状态不持久化——杜绝测试种子泄漏到生产会话的残留风险，
        也因此不提供"种子查询"（回复与审计日志即状态记录）。
        """
        token = args.strip()
        if token == "重置":
            random.seed()
            return True, (
                "✅ 已恢复系统熵随机源，后续随机行为不再按固定序列产出。\n"
                "⚠️ 仅限测试场景使用。"
            )

        value = self._parse_int(token)
        if value is None:
            return False, (
                "❌ 参数错误：/修仙GM 随机种子 <整数> 设定固定种子，"
                "或 /修仙GM 随机种子 重置 恢复随机。"
            )

        random.seed(value)
        return True, (
            f"✅ 已设定全局随机种子：{value}\n"
            "⚠️ 仅限测试场景：进程级生效——同进程所有使用全局 random 的组件"
            "（含宿主其他插件）都进入固定序列；「随机种子 重置」或重启进程即恢复。\n"
            "💡 与测试平台 deterministic+seed 同机制（双方都重置全局种子），"
            "后执行者生效：平台用例开启 deterministic 时会在每次 send 前覆盖 GM 种子。"
        )
