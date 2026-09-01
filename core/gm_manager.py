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

    from ..core import EquipmentManager, StorageRingManager


# 日志文件大小阈值：500 MB
LOG_MAX_SIZE_BYTES = 500 * 1024 * 1024

# 「时间快进」字段覆盖清单（OpenSpec gm-test-time-and-rng-controls design D2
# 显式枚举）。每条 = (回复域名, UPDATE 语句)，语句中的每个 ? 都以前移秒数填充。
# 原则：只前移参与到期/冷却判定的时间戳；历史记录类时间戳（交易流水、日志、
# 创建时间）一律不动。首版不覆盖的已知域见 design D2（丹药 buff、商店刷新、
# 灵田、洞天/灵眼收取、双修请求过期等），均不阻碍冷却类测试主链路。
# 约束：新增等待类冷却域时必须同步补充本清单与 GM 帮助文本（AGENTS.md §2）。
_TIME_SKIP_RULES: tuple[tuple[str, str], ...] = (
    (
        "历练/秘境/宗门任务计划完成时间",
        "UPDATE user_cd SET scheduled_time = scheduled_time - ? "
        "WHERE type != 0 AND scheduled_time > 0",
    ),
    (
        "闭关开始时间",
        "UPDATE players SET cultivation_start_time = cultivation_start_time - ? "
        "WHERE state = '修炼中' AND cultivation_start_time > 0",
    ),
    (
        "决斗/切磋冷却",
        "UPDATE combat_cooldowns SET last_duel_time = last_duel_time - ?, "
        "last_spar_time = last_spar_time - ? "
        "WHERE last_duel_time > 0 OR last_spar_time > 0",
    ),
    (
        "双修冷却",
        "UPDATE dual_cultivation SET last_dual_time = last_dual_time - ? "
        "WHERE last_dual_time > 0",
    ),
    (
        "进行中悬赏过期时间",
        "UPDATE bounty_tasks SET expire_time = expire_time - ? WHERE status = 1",
    ),
    (
        "贷款到期时间",
        "UPDATE bank_loans SET due_at = due_at - ? WHERE status = 'active'",
    ),
    # system_config 的 value 为 TEXT：CAST 守卫只前移正整数时间戳，
    # 非数值/已归零配置项不受影响（TEXT 列亲和性会把算回的结果存回文本）
    (
        "悬赏放弃冷却",
        "UPDATE system_config "
        "SET value = CAST(CAST(value AS INTEGER) - ? AS TEXT) "
        "WHERE key LIKE 'bounty_abandon_cd_%' AND CAST(value AS INTEGER) > 0",
    ),
    (
        "Boss/灵眼下次刷新时间",
        "UPDATE system_config "
        "SET value = CAST(CAST(value AS INTEGER) - ? AS TEXT) "
        "WHERE key IN ('boss_next_spawn_time', 'spirit_eye_next_spawn_time') "
        "AND CAST(value AS INTEGER) > 0",
    ),
    (
        "传承挑战冷却",
        "UPDATE impart_pk_cooldown SET failed_at = failed_at - ? WHERE failed_at > 0",
    ),
    (
        "传承被夺保护期",
        "UPDATE impart_snatch_protection SET snatched_at = snatched_at - ? "
        "WHERE snatched_at > 0",
    ),
)


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
        self.plugin_data_path = plugin_data_path
        self.broadcast_callback = broadcast_callback

        # 子命令路由表
        self._commands = {
            "帮助": self.cmd_help,
            "设置境界": self.cmd_set_level,
            "设置修为": self.cmd_set_experience,
            "设置灵石": self.cmd_set_gold,
            "设置气血": self.cmd_set_hp,
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
            "触发秘境结算": self.cmd_force_rift,
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
        help_text = (
            "🔧 修仙GM 指令大全\n"
            "━━━━━━━━━━━━━━━\n"
            "\n"
            "📖 角色属性\n"
            "  设置境界 [@玩家/ID] <境界名>\n"
            "  设置修为 [@玩家/ID] <数值>\n"
            "  设置灵石 [@玩家/ID] <数值>\n"
            "  设置气血 [@玩家/ID] <数值>\n"
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
            "  触发历练结算 [@玩家/ID]\n"
            "  触发秘境结算 [@玩家/ID]\n"
            "\n"
            "👹 系统\n"
            "  生成Boss\n"
            "\n"
            "🧪 测试工具（⚠️ 仅限测试实例）\n"
            "  时间快进 <秒> 确认 （全库到期类时间戳前移，不可逆；不唤醒睡眠中的定时任务，\n"
            "    Boss/灵眼下轮醒来即触发，需要立即生成请用「生成Boss」；前移贷款到期会真实触发逾期追杀）\n"
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
            return True, f"✅ 已推进师承任务：{master_msg}"
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
        """GM command: set the target player's hp."""
        return await self._set_numeric_attr(event, args, "气血", "hp", "气血")

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
                f"❌ 请输入{item_kind}名称，例如：/修仙GM 给予{item_kind} 青锋剑",
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
            return False, f"❌ 卸下失败：{msg}"

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
            f"✅ 已卸下【{player.user_name or target_id}】的 {slot_or_name}：{msg}{store_msg}",
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

        await self.db.ext.set_user_free(target_id)
        player.state = "空闲"
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

        cleared = []
        active = await self.db.ext.get_active_bounty(target_id)
        if active:
            await self.db.ext.cancel_bounty(target_id)
            cleared.append(f"进行中悬赏【{active['bounty_name']}】")

        cd_key = f"bounty_abandon_cd_{target_id}"
        if await self.db.ext.get_system_config(cd_key):
            await self.db.ext.set_system_config(cd_key, "0")
            cleared.append("放弃冷却")

        if not cleared:
            return (
                False,
                f"❌ 【{player.user_name or target_id}】没有可清除的悬赏状态！",
            )
        return (
            True,
            f"✅ 已清除【{player.user_name or target_id}】的{'、'.join(cleared)}",
        )

    async def cmd_force_adventure(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制历练结算。"""
        # 强制结算类命令的参数即目标 ID：单个数字也视为目标（
        # 通用规则会将单个数字当作命令自身数值参数而回落到发送者）。
        tokens = args.split() if args else []
        if tokens and tokens[0].lstrip("@").isdigit():
            target_id = tokens[0].lstrip("@")
        else:
            target_id, _ = self._resolve_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(target_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 目标玩家当前不在历练中！"

        if not self.adventure_manager:
            return False, "❌ 历练管理器未初始化！"

        # 将计划完成时间提前到当前时间，立即结算
        user_cd.scheduled_time = int(time.time())
        await self.db.ext.update_user_cd(user_cd)

        success, msg, reward_data = await self.adventure_manager.finish_adventure(
            target_id
        )
        if not success:
            return False, f"❌ 历练结算失败：{msg}"

        # 强制结算即"立即完成"：同时清除该玩家的历练路线休整冷却，
        # 允许测试脚本连续开启同一路线（正常流程仍按配置冷却）。
        if self.adventure_manager:
            self.adventure_manager._route_cooldowns.pop(target_id, None)

        # 更新悬赏进度（与正常 /完成历练 保持一致）
        if reward_data and self.bounty_manager:
            bounty_tag = reward_data.get("bounty_tag", "adventure")
            bounty_value = reward_data.get("bounty_progress", 1)
            has_progress, bounty_msg = await self.bounty_manager.add_bounty_progress(
                player, bounty_tag, bounty_value
            )
            if has_progress:
                msg += bounty_msg

        # 师承任务链：与 main.py handle_adventure_complete 保持一致——
        # 历练完成与 PvE 胜利各自独立推进，任一失败不影响另一条反馈。
        master_msg = None
        try:
            master_msg = await self.sect_manager.advance_master_progress(
                target_id, "adventure_complete"
            )
        except Exception:
            logger.warning(
                "【修仙插件】师承任务进度推进失败（强制历练完成）", exc_info=True
            )
        if (reward_data or {}).get("pve_won"):
            try:
                win_msg = await self.sect_manager.advance_master_progress(
                    target_id, "win_pve"
                )
                if win_msg:
                    master_msg = (master_msg or "") + win_msg
            except Exception:
                logger.warning(
                    "【修仙插件】师承任务进度推进失败（强制历练PvE胜利）", exc_info=True
                )
        if master_msg:
            msg += master_msg

        return True, f"✅ 已强制结算【{player.user_name or target_id}】的历练\n{msg}"

    async def cmd_force_rift(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制秘境结算。"""
        # 强制结算类命令的参数即目标 ID：单个数字也视为目标（
        # 通用规则会将单个数字当作命令自身数值参数而回落到发送者）。
        tokens = args.split() if args else []
        if tokens and tokens[0].lstrip("@").isdigit():
            target_id = tokens[0].lstrip("@")
        else:
            target_id, _ = self._resolve_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(target_id)
        if not user_cd or user_cd.type != UserStatus.EXPLORING:
            return False, "❌ 目标玩家当前不在秘境探索中！"

        if not self.rift_manager:
            return False, "❌ 秘境管理器未初始化！"

        # 将计划完成时间提前到当前时间，立即结算
        user_cd.scheduled_time = int(time.time())
        await self.db.ext.update_user_cd(user_cd)

        success, msg, reward_data = await self.rift_manager.finish_exploration(
            target_id
        )
        if not success:
            return False, f"❌ 秘境结算失败：{msg}"

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

    async def cmd_spawn_boss(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """生成世界 Boss。"""
        if not self.boss_manager:
            return False, "❌ Boss管理器未初始化！"

        success, msg, boss = await self.boss_manager.auto_spawn_boss()
        if not success:
            return False, f"❌ 生成Boss失败：{msg}"

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
        """时间快进：将枚举清单内的到期判定时间戳统一前移 N 秒（design D1/D2）。

        直接改写数据库字段（与 cmd_force_adventure 改 scheduled_time 同一先例），
        让业务逻辑在「时间已到」的真实状态下运行——不是绕过结算逻辑。
        不承诺唤醒 asyncio.sleep 中的定时任务（Boss/灵眼循环下次醒来读到
        已前移的刷新时间即触发）。前移不可逆，故沿用「确认」约定。
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
        counts: list[tuple[str, int]] = []
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            for label, sql in _TIME_SKIP_RULES:
                params = (seconds,) * sql.count("?")
                async with self.db.conn.execute(sql, params) as cursor:
                    counts.append((label, max(cursor.rowcount, 0)))
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        detail = "\n".join(f"  {label}：{count} 条" for label, count in counts)
        total = sum(count for _, count in counts)
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

        # 1. 忙碌状态（同「清除CD」）：user_cd 与 player.state 双层同步复位
        user_cd = await self.db.ext.get_user_cd(target_id)
        if (user_cd and user_cd.type != UserStatus.IDLE) or player.state != "空闲":
            await self.db.ext.set_user_free(target_id)
            player.state = "空闲"
            await self.db.update_player(player)
            cleared.append("忙碌状态：1 条")

        # 2. 决斗/切磋冷却清零（无 ext 方法，与 combat_handlers 一样直连 conn）
        async with self.db.conn.execute(
            "UPDATE combat_cooldowns SET last_duel_time = 0, last_spar_time = 0 "
            "WHERE user_id = ? AND (last_duel_time > 0 OR last_spar_time > 0)",
            (target_id,),
        ) as cursor:
            combat_cleared = cursor.rowcount
        await self.db.conn.commit()
        if combat_cleared:
            cleared.append(f"决斗/切磋冷却：{combat_cleared} 条")

        # 3. 双修冷却清零
        async with self.db.conn.execute(
            "UPDATE dual_cultivation SET last_dual_time = 0 "
            "WHERE user_id = ? AND last_dual_time > 0",
            (target_id,),
        ) as cursor:
            dual_cleared = cursor.rowcount
        await self.db.conn.commit()
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

        # 6. 历练路线休整冷却（内存态不落库，同 cmd_force_adventure 的弹出方式）
        if self.adventure_manager:
            popped = self.adventure_manager._route_cooldowns.pop(target_id, None)
            if popped:
                cleared.append(f"历练路线休整冷却：{len(popped)} 条")

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
