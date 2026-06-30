"""GM 管理器 - 处理修仙插件的管理员命令。"""

import json
import os
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

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent

    from ..core import EquipmentManager, StorageRingManager


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
    ):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = storage_ring_manager
        self.equipment_manager = equipment_manager
        self.adventure_manager = adventure_manager
        self.rift_manager = rift_manager
        self.boss_manager = boss_manager
        self.bounty_manager = bounty_manager
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
            "给予装备": self.cmd_give_equipment,
            "给予物品": self.cmd_give_item,
            "卸下装备": self.cmd_unequip,
            "清除cd": self.cmd_clear_cd,
            "清除CD": self.cmd_clear_cd,
            "触发历练结算": self.cmd_force_adventure,
            "触发秘境结算": self.cmd_force_rift,
            "生成boss": self.cmd_spawn_boss,
            "生成Boss": self.cmd_spawn_boss,
            "生成BOSS": self.cmd_spawn_boss,
        }

    # ========== 通用工具 ==========

    def _resolve_target(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[str | None, str]:
        """解析目标玩家。

        优先级：
        1. 消息中的 @mention
        2. 参数中的纯数字 user_id
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
        # 规则：仅当剩余参数不少于 2 个时，第一个数字 token 才被视为目标 ID；
        # 否则将该数字视为命令本身的数值参数（省略了目标）。
        tokens = args.split() if args else []
        if len(tokens) >= 2 and tokens[0].lstrip("@").isdigit():
            target_id = tokens[0].lstrip("@")
            remaining = " ".join(tokens[1:])
            return target_id, remaining

        # 3. 未指定目标，默认使用发送者
        sender_id = str(event.get_sender_id()) if event.get_sender_id() else None
        return sender_id, args

    async def _get_player(self, user_id: str) -> Player | None:
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
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _item_exists(self, item_name: str) -> bool:
        """检查物品是否存在于配置中。"""
        if item_name in self.config_manager.items_data:
            return True
        if item_name in self.config_manager.weapons_data:
            return True
        return False

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
            "  设置真元 [@玩家/ID] <数值>\n"
            "  设置攻击 [@玩家/ID] <数值>\n"
            "  设置精神力 [@玩家/ID] <数值>\n"
            "\n"
            "🎒 装备物品\n"
            "  给予装备 [@玩家/ID] <物品名> [数量]\n"
            "  给予物品 [@玩家/ID] <物品名> [数量]\n"
            "  卸下装备 [@玩家/ID] <槽位/名称>\n"
            "\n"
            "⏱ 状态与结算\n"
            "  清除CD [@玩家/ID] 确认\n"
            "  触发历练结算 [@玩家/ID]\n"
            "  触发秘境结算 [@玩家/ID]\n"
            "\n"
            "👹 系统\n"
            "  生成Boss\n"
            "\n"
            "💡 目标玩家可省略，默认作用于发送者；\n"
            "💡 带 [] 的参数可省略，<> 为必填。"
        )
        return True, help_text

    async def cmd_set_level(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """设置境界。"""
        target_id, remaining = self._resolve_target(event, args)
        player = await self._get_player(target_id)
        if not player:
            return False, "❌ 目标玩家尚未踏入修仙之路！"

        realm_name = remaining.strip()
        if not realm_name:
            return False, "❌ 请输入境界名称，例如：/修仙GM 设置境界 筑基期初期"

        level_data = self.config_manager.get_level_data(player.cultivation_type)
        found_index = None
        for idx, data in enumerate(level_data):
            if data.get("level_name") == realm_name:
                found_index = idx
                break

        if found_index is None:
            valid_names = [
                d.get("level_name", "") for d in level_data if d.get("level_name")
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
        return await self._set_numeric_attr(event, args, "修为", "experience", "修为")

    async def cmd_set_gold(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._set_numeric_attr(event, args, "灵石", "gold", "灵石")

    async def cmd_set_hp(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._set_numeric_attr(event, args, "气血", "hp", "气血")

    async def cmd_set_mp(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._set_numeric_attr(event, args, "真元", "mp", "真元")

    async def cmd_set_atk(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._set_numeric_attr(event, args, "攻击", "atk", "攻击")

    async def cmd_set_mental_power(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._set_numeric_attr(
            event, args, "精神力", "mental_power", "精神力"
        )

    async def cmd_give_equipment(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._give_item(event, args, "装备")

    async def cmd_give_item(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        return await self._give_item(event, args, "物品")

    async def _give_item(
        self, event: "AstrMessageEvent", args: str, item_kind: str
    ) -> tuple[bool, str]:
        """给予物品或装备（进储物戒）。"""
        target_id, remaining = self._resolve_target(event, args)
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
        target_id, remaining = self._resolve_target(event, args)
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

    async def cmd_force_adventure(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制历练结算。"""
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

        # 更新悬赏进度（与正常 /完成历练 保持一致）
        if reward_data and self.bounty_manager:
            bounty_tag = reward_data.get("bounty_tag", "adventure")
            bounty_value = reward_data.get("bounty_progress", 1)
            has_progress, bounty_msg = await self.bounty_manager.add_bounty_progress(
                player, bounty_tag, bounty_value
            )
            if has_progress:
                msg += bounty_msg

        return True, f"✅ 已强制结算【{player.user_name or target_id}】的历练\n{msg}"

    async def cmd_force_rift(
        self, event: "AstrMessageEvent", args: str
    ) -> tuple[bool, str]:
        """强制秘境结算。"""
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
