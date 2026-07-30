# managers/impart_manager.py
"""Impart (inheritance) system manager.

The legacy percentage-based buffs (HP/MP/ATK/know/burst) have been removed.
Impart is now a single ``impart_value`` accumulated through PK challenges.
Reaching configured tier thresholds automatically grants tier rewards:
- heart_method: stores a heart-method item in the player's storage ring
- technique: directly learns a skill into player_skills (source="impart")
- level_up: raises the player's level_index by a fixed amount (capped)
"""

from astrbot.api import logger

from ..config_manager import ConfigManager
from ..data.data_manager import DataBase
from ..models import Player
from ..models_extended import ImpartInfo


class ImpartManager:
    """Manager for the impart (inheritance) value and tier rewards."""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager

    def _get_tiers_config(self) -> list[dict]:
        """Return the sorted list of impart tier definitions."""
        tiers = self.config_manager.impart_config.get("tiers", [])
        return sorted(tiers, key=lambda t: t.get("tier", 0))

    def _calculate_tier(self, impart_value: int) -> int:
        """Return the highest tier reached for the given impart value."""
        tier = 0
        for t in self._get_tiers_config():
            if impart_value >= t.get("impart_value_required", 0):
                tier = t.get("tier", 0)
            else:
                break
        return tier

    def _find_heart_method(self, reward_id: str) -> dict | None:
        """Find a heart-method definition by name or id."""
        data = self.config_manager.heart_methods_data
        if reward_id in data:
            return data[reward_id]
        for item in data.values():
            if isinstance(item, dict) and item.get("id") == reward_id:
                return item
        return None

    def _find_skill_by_id(self, skill_id: str) -> dict | None:
        """Find a skill definition by its id across all skill groups."""
        for item in self.config_manager.skills_data.values():
            if isinstance(item, dict) and item.get("id") == skill_id:
                return item
        return None

    def _max_level_index(self) -> int:
        """Return the highest valid level index across both routes."""
        return (
            max(
                len(self.config_manager.level_data),
                len(self.config_manager.body_level_data),
            )
            - 1
        )

    def _build_panel(self, impart_info: ImpartInfo) -> str:
        """Build the Chinese info panel for a player's impart state."""
        tiers = self._get_tiers_config()
        current_tier = self._calculate_tier(impart_info.impart_value)
        claimed = impart_info.get_claimed_tiers()

        next_tier = None
        for t in tiers:
            if t.get("tier", 0) > current_tier:
                next_tier = t
                break

        if next_tier:
            required = next_tier.get("impart_value_required", 0)
            progress = min(
                100,
                int(impart_info.impart_value / required * 100) if required else 0,
            )
            next_line = (
                f"下一阶：第{next_tier['tier']}阶 "
                f"（需{required}传承值，进度{progress}%）"
            )
        else:
            next_line = "下一阶：已达最高等阶"

        claimed_text = ", ".join(str(t) for t in claimed) if claimed else "无"

        return (
            "✨ 传承信息\n"
            "━━━━━━━━━━━━━━━\n"
            f"传承值：{impart_info.impart_value}\n"
            f"当前等阶：第{current_tier}阶\n"
            f"{next_line}\n"
            f"已领取等阶：{claimed_text}"
        )

    async def get_impart_info(
        self, user_id: str
    ) -> tuple[bool, str, ImpartInfo | None]:
        """Get the impart info panel and auto-grant any pending rewards."""
        impart_info = await self.db.ext.get_impart_info(user_id)
        if not impart_info:
            return False, "❌ 你还未开启传承系统！", None

        player = await self.db.get_player_by_id(user_id)
        if player:
            granted = await self._grant_pending_rewards(player)
            if granted:
                # Reload to reflect newly claimed tiers in the panel.
                impart_info = await self.db.ext.get_impart_info(user_id)
                panel = self._build_panel(impart_info)
                panel += "\n🎁 自动发放奖励：\n" + "\n".join(granted)
                return True, panel, impart_info

        return True, self._build_panel(impart_info), impart_info

    async def add_impart_value(self, user_id: str, delta: int) -> tuple[bool, str]:
        """Add impart value to a user and trigger tier reward checks."""
        if delta <= 0:
            return False, "❌ 传承值变化无效"

        impart_info = await self.db.ext.get_impart_info(user_id)
        if not impart_info:
            await self.db.ext.create_impart_info(user_id)
            impart_info = await self.db.ext.get_impart_info(user_id)

        impart_info.impart_value += delta
        await self.db.ext.update_impart_info(impart_info)

        player = await self.db.get_player_by_id(user_id)
        granted_msgs: list[str] = []
        if player:
            granted_msgs = await self._grant_pending_rewards(player)
            # Reload impart info after reward grants may have updated claimed tiers.
            impart_info = await self.db.ext.get_impart_info(user_id)

        msg = f"✨ 传承值 +{delta}，当前传承值：{impart_info.impart_value}"
        if granted_msgs:
            msg += "\n🎁 解锁奖励：\n" + "\n".join(granted_msgs)
        return True, msg

    async def _grant_pending_rewards(self, player: Player) -> list[str]:
        """Grant all unclaimed tier rewards the player has reached.

        Returns a list of Chinese reward messages for any newly granted rewards.
        """
        impart_info = await self.db.ext.get_impart_info(player.user_id)
        if not impart_info:
            return []

        tiers = self._get_tiers_config()
        current_tier = self._calculate_tier(impart_info.impart_value)
        claimed = set(impart_info.get_claimed_tiers())
        granted: list[str] = []
        player_changed = False

        for tier in tiers:
            tier_number = tier.get("tier", 0)
            if tier_number > current_tier or tier_number in claimed:
                continue

            for reward in tier.get("rewards", []):
                reward_msg = await self._grant_reward(player, reward)
                if reward_msg:
                    granted.append(reward_msg)
                    player_changed = True

            claimed.add(tier_number)

        if claimed != set(impart_info.get_claimed_tiers()):
            impart_info.set_claimed_tiers(sorted(claimed))
            await self.db.ext.update_impart_info(impart_info)

        if player_changed:
            await self.db.update_player(player)

        return granted

    async def _grant_reward(self, player: Player, reward: dict) -> str | None:
        """Apply a single reward and return a Chinese message, or None on skip."""
        reward_type = reward.get("type")
        reward_id = reward.get("id", "")

        if reward_type == "heart_method":
            heart_method = self._find_heart_method(reward_id)
            if not heart_method:
                logger.warning(f"[impart] unknown heart_method reward: {reward_id}")
                return None
            name = heart_method.get("name", reward_id)
            items = player.get_storage_ring_items()
            items[name] = items.get(name, 0) + 1
            player.set_storage_ring_items(items)
            return f"获得传承心法【{name}】"

        if reward_type == "technique":
            skill_id = reward_id
            skill_def = self._find_skill_by_id(skill_id)
            if not skill_def:
                logger.warning(f"[impart] unknown technique reward: {skill_id}")
                return None
            is_new, star = await self.db.ext.learn_or_star_up(
                player.user_id, skill_id, "impart"
            )
            name = skill_def.get("name", skill_id)
            if is_new:
                return f"领悟传承功法【{name}】"
            return f"传承功法【{name}】升星至{star}星"

        if reward_type == "level_up":
            amount = reward.get("amount", 1)
            max_level = self._max_level_index()
            old_level = player.level_index
            new_level = min(old_level + amount, max_level)
            if new_level > old_level:
                player.level_index = new_level
                return f"境界提升 {new_level - old_level} 层"
            return "已达境界上限"

        logger.warning(f"[impart] unknown reward type: {reward_type}")
        return None
