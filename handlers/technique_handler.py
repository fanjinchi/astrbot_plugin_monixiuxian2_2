# handlers/technique_handler.py
"""Technique / skill system command handlers.

Handles study target management and battle report merge count preference.
"""

from astrbot.api.event import AstrMessageEvent

from ..config_manager import ConfigManager
from ..core import SkillManager, StorageRingManager
from ..data import DataBase
from ..models import Player
from .utils import player_required

CMD_SET_STUDY_TARGET = "修习目标"
CMD_SHOW_STUDY_TARGET = "我的修习"
CMD_CLEAR_STUDY_TARGET = "取消修习"
CMD_SET_BATTLE_REPORT_COUNT = "战报条数"
CMD_ACTIVATE_TECHNIQUE = "激活功法"
CMD_DEACTIVATE_TECHNIQUE = "卸下功法"
CMD_MY_SKILLS = "我的技能"

__all__ = ["TechniqueHandler"]


class TechniqueHandler:
    """功法/修习目标处理器"""

    def __init__(
        self,
        db: DataBase,
        config_manager: ConfigManager,
        skill_manager: SkillManager,
        storage_ring_mgr: StorageRingManager,
    ):
        self.db = db
        self.config_manager = config_manager
        self.skill_manager = skill_manager
        self.storage_ring_mgr = storage_ring_mgr

    def _get_owned_skill_ids(self, player: Player) -> list[str]:
        """Collect skill IDs owned by the player (inventory + equipped).

        Args:
            player: Player object.

        Returns:
            List of owned skill IDs.
        """
        owned_names: set[str] = set()

        # Items currently in the storage ring
        try:
            owned_names.update(player.get_storage_ring_items().keys())
        except Exception:
            pass

        # Equipped gear / techniques
        owned_names.update(player.get_techniques_list())
        if player.weapon:
            owned_names.add(player.weapon)
        if player.armor:
            owned_names.add(player.armor)
        if player.main_technique:
            owned_names.add(player.main_technique)

        owned_ids: list[str] = []
        for name in owned_names:
            skill_id = self.skill_manager._find_skill_id_by_name(name)
            if skill_id:
                owned_ids.append(skill_id)
        return owned_ids

    @player_required
    async def handle_set_study_target(
        self, player: Player, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Set an owned but not-yet-learned technique as the study target."""
        if not skill_name or not skill_name.strip():
            yield event.plain_result(
                f"请指定要设为修习目标的功法名称\n用法：{CMD_SET_STUDY_TARGET} 功法名"
            )
            return

        skill_name = skill_name.strip()
        skill_id = self.skill_manager._find_skill_id_by_name(skill_name)
        if not skill_id:
            yield event.plain_result(f"未找到功法【{skill_name}】")
            return

        owned_ids = self._get_owned_skill_ids(player)
        if skill_id not in owned_ids:
            yield event.plain_result(
                f"❌ 你尚未拥有功法【{skill_name}】，无法设为修习目标"
            )
            return

        ok, msg = await self.skill_manager.set_study_target(
            player, skill_id, owned_ids
        )
        if ok:
            await self.db.update_player(player)
            yield event.plain_result(f"✅ {msg}")
        else:
            yield event.plain_result(f"❌ {msg}")

    @player_required
    async def handle_show_study_target(self, player: Player, event: AstrMessageEvent):
        """Display the current study target."""
        info = self.skill_manager.get_study_target_info(player)
        if info.get("has_target"):
            name = info.get("name", "未知")
            description = info.get("description", "")
            text = f"🎯 当前修习目标：【{name}】"
            if description:
                text += f"\n{description}"
            yield event.plain_result(text)
        else:
            yield event.plain_result("当前没有修习目标")

    @player_required
    async def handle_clear_study_target(self, player: Player, event: AstrMessageEvent):
        """Clear the current study target."""
        ok, msg = self.skill_manager.clear_study_target(player)
        if ok:
            await self.db.update_player(player)
            yield event.plain_result(f"✅ {msg}")
        else:
            yield event.plain_result(f"❌ {msg}")

    @player_required
    async def handle_set_battle_report_count(
        self, player: Player, event: AstrMessageEvent, count: str = ""
    ):
        """Set the player's preferred battle report merge count (1-50)."""
        count = count.strip() if count else ""
        if not count.isdigit():
            yield event.plain_result(
                f"请指定 1-50 之间的数字\n用法：{CMD_SET_BATTLE_REPORT_COUNT} 10"
            )
            return

        value = int(count)
        if value < 1 or value > 50:
            yield event.plain_result("战报合并条数必须在 1-50 之间")
            return

        player.battle_report_merge_count = value
        await self.db.update_player(player)
        yield event.plain_result(f"✅ 战报合并条数已设置为 {value}")

    @player_required
    async def handle_activate_technique(
        self, player: Player, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Activate a learned technique into the active technique slots."""
        if not skill_name or not skill_name.strip():
            yield event.plain_result(
                f"请指定要激活的功法名称\n用法：{CMD_ACTIVATE_TECHNIQUE} 功法名"
            )
            return

        skill_name = skill_name.strip()
        skill_id = self.skill_manager._find_skill_id_by_name(skill_name)
        if not skill_id:
            yield event.plain_result(f"未找到功法【{skill_name}】")
            return

        if not await self.skill_manager._is_skill_learned(player, skill_id):
            yield event.plain_result(
                f"❌ 功法【{skill_name}】尚未领悟，无法激活\n"
                f"💡 可先将功法物品设为修习目标进行领悟"
            )
            return

        techniques = player.get_techniques_list()
        if skill_name in techniques:
            yield event.plain_result(f"❌ 功法【{skill_name}】已处于激活状态")
            return

        max_slots = self.skill_manager._skill_cfg.get("max_technique_slots", 4)
        if len(techniques) >= max_slots:
            yield event.plain_result(
                f"❌ 功法激活栏已满（最多{max_slots}个），请先卸下其他功法"
            )
            return

        techniques.append(skill_name)
        player.set_techniques_list(techniques)
        await self.db.update_player(player)
        yield event.plain_result(
            f"✅ 已激活功法【{skill_name}】（{len(techniques)}/{max_slots}）"
        )

    @player_required
    async def handle_deactivate_technique(
        self, player: Player, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Remove a technique from the active technique slots."""
        if not skill_name or not skill_name.strip():
            yield event.plain_result(
                f"请指定要卸下的功法名称\n用法：{CMD_DEACTIVATE_TECHNIQUE} 功法名"
            )
            return

        skill_name = skill_name.strip()
        techniques = player.get_techniques_list()
        if skill_name not in techniques:
            yield event.plain_result(f"❌ 功法【{skill_name}】未在激活列表中")
            return

        techniques.remove(skill_name)
        player.set_techniques_list(techniques)
        await self.db.update_player(player)
        yield event.plain_result(f"✅ 已卸下功法【{skill_name}】")

    @player_required
    async def handle_my_skills(self, player: Player, event: AstrMessageEvent):
        """Display the player's learned skills and active techniques."""
        max_slots = self.skill_manager._skill_cfg.get("max_technique_slots", 4)
        active = player.get_techniques_list()
        learned = await self.db.ext.get_learned_skills(player.user_id)
        study_info = self.skill_manager.get_study_target_info(player)

        lines = ["📜 我的功法", "━━━━━━━━━━━━━━━"]
        lines.append(f"【已激活】{len(active)}/{max_slots}")
        if active:
            for name in active:
                lines.append(f"  • {name}")
        else:
            lines.append("  暂无激活功法")

        lines.append("")
        lines.append(f"【已领悟】{len(learned)}个")
        if learned:
            for entry in learned:
                skill_id = entry.get("skill_id", "")
                star = entry.get("star_level", 1)
                source = entry.get("source", "")
                name = self.skill_manager._get_skill_name(skill_id)
                source_display = source if source else "未知"
                lines.append(f"  • {name} | 星级：{star} | 来源：{source_display}")
        else:
            lines.append("  暂无已领悟功法")

        lines.append("")
        if study_info.get("has_target"):
            lines.append(f"【修习目标】{study_info.get('name', '未知')}")
        else:
            lines.append("【修习目标】无")

        lines.append("━━━━━━━━━━━━━━━")
        yield event.plain_result("\n".join(lines))
