# managers/impart_manager.py
"""Impart (legacy) system manager — multi-instance rework (v32).

A legacy is an instance (``legacy_instances`` row) with a type
(common/sect/adventure/rift), an owner, an impart value and claimed tiers.
Impart value accumulates ONLY through cultivation (1 point per 15 effective
minutes, applied to the player's single active instance on settlement).
PK merely transfers instance ownership (winner takes it, value/tiers reset).

Tier rewards (per legacy type, from ``impart_config.json`` ``types``):
- heart_method: stores a heart-method item in the player's storage ring
- technique: directly learns a skill into player_skills (source="impart")
- level_up: raises the player's level_index by a fixed amount (capped)
"""

import time

from astrbot.api import logger

from ..config_manager import ConfigManager
from ..data.data_manager import DataBase
from ..models import Player
from ..models_extended import LegacyInstance

# 失败冷却：挑战者失败后 5 天内不得再次向同一目标发起传承挑战。
IMPART_PK_COOLDOWN_SECONDS = 5 * 86400
# 被夺保护：传承被夺走的玩家 3 天内不可被任何玩家发起传承挑战。
IMPART_SNATCH_PROTECTION_SECONDS = 3 * 86400

LEGACY_TYPE_NAMES = {
    "common": "通用传承",
    "sect": "宗门传承",
    "adventure": "历练传承",
    "rift": "秘境传承",
}


class ImpartManager:
    """Manager for legacy instances, activation, tier rewards, cooldowns."""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager

    # ===== 配置读取 =====

    def _get_type_config(self, legacy_type: str) -> dict:
        """Return the config block (name/tiers) for a legacy type."""
        return self.config_manager.impart_config.get("types", {}).get(legacy_type) or {}

    def _get_tiers_config(self, legacy_type: str) -> list[dict]:
        """Return the sorted tier definitions for a legacy type."""
        tiers = self._get_type_config(legacy_type).get("tiers", [])
        return sorted(tiers, key=lambda t: t.get("tier", 0))

    def get_type_name(self, legacy_type: str) -> str:
        """Return the display name of a legacy type."""
        return self._get_type_config(legacy_type).get(
            "name", LEGACY_TYPE_NAMES.get(legacy_type, legacy_type)
        )

    def _calculate_tier(self, legacy_type: str, impart_value: int) -> int:
        """Return the highest tier reached for the given value."""
        tier = 0
        for t in self._get_tiers_config(legacy_type):
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
        return max(
            self.config_manager.get_max_level("灵修"),
            self.config_manager.get_max_level("体修"),
        )

    # ===== 实例 CRUD / 激活 =====

    async def create_legacy(
        self,
        owner_id: str,
        legacy_type: str,
        sect_id: int | None = None,
        activate: bool = True,
        commit: bool = True,
    ) -> LegacyInstance | None:
        """Create a legacy instance for a player.

        Args:
            owner_id: Owning player user ID.
            legacy_type: One of common/sect/adventure/rift.
            sect_id: Owning sect for sect-type legacies, else None.
            activate: When True (default), the new instance becomes the
                player's active one; when False (e.g. snatched legacies),
                activation is left untouched.
            commit: Whether to commit immediately; False inside outer txn.

        Returns:
            The created instance, or None on failure.
        """
        instance_id = await self.db.ext.create_legacy_instance(
            owner_id, legacy_type, sect_id=sect_id, is_active=False, commit=commit
        )
        if not instance_id:
            return None
        if activate:
            if commit:
                await self.db.ext.set_active_legacy_instance(owner_id, instance_id)
            else:
                # 外层事务内：手动去激+激活，不另起事务
                await self.db.conn.execute(
                    "UPDATE legacy_instances SET is_active = 0 WHERE owner_id = ?",
                    (owner_id,),
                )
                await self.db.conn.execute(
                    "UPDATE legacy_instances SET is_active = 1 WHERE id = ?",
                    (instance_id,),
                )
        return await self.db.ext.get_legacy_instance_by_id(instance_id)

    async def list_owner_legacies(self, user_id: str) -> list[LegacyInstance]:
        """List all legacy instances held by the player (newest first)."""
        return await self.db.ext.list_legacy_instances_by_owner(user_id)

    async def get_active_legacy(self, user_id: str) -> LegacyInstance | None:
        """Return the player's currently active legacy instance, if any."""
        return await self.db.ext.get_active_legacy_instance(user_id)

    async def activate_legacy(self, user_id: str, instance_id: int) -> tuple[bool, str]:
        """Activate one of the player's instances for cultivation accumulation."""
        ok = await self.db.ext.set_active_legacy_instance(user_id, instance_id)
        if not ok:
            return False, "❌ 未找到你持有的该传承！"
        instance = await self.db.ext.get_legacy_instance_by_id(instance_id)
        name = self.get_type_name(instance.legacy_type)
        return True, f"✨ 已激活【{name}】（编号{instance_id}），出关时将向其累积传承值"

    # ===== 传承值累积（仅激活实例） =====

    async def add_active_impart_value(
        self, player: Player, delta: int, commit: bool = True
    ) -> str | None:
        """Add impart value to the player's ACTIVE instance (cultivation hook).

        Args:
            player: The settling player (for tier reward grants).
            delta: Points to add (effective_minutes // 15); <=0 is a no-op.
            commit: Whether instance updates commit immediately; True by
                default since the cultivation settlement calls this outside
                any transaction. Reward persistence always commits via
                ``update_player``.

        Returns:
            A Chinese message line for the settlement report, or None when
            the player holds no legacy / none is active.
        """
        if delta <= 0:
            return None
        instance = await self.db.ext.get_active_legacy_instance(player.user_id)
        if not instance:
            return None

        instance.impart_value += delta
        await self.db.ext.update_legacy_instance(instance, commit=commit)

        granted = await self._grant_pending_rewards(player, instance, commit=commit)
        name = self.get_type_name(instance.legacy_type)
        msg = f"🌟 【{name}】传承值 +{delta}（当前 {instance.impart_value}）"
        if granted:
            msg += "\n🎁 解锁奖励：\n" + "\n".join(granted)
        return msg

    # ===== PK 夺取 =====

    async def select_snatch_target(
        self, defender_id: str, legacy_type: str | None = None
    ) -> LegacyInstance | None:
        """Pick the defender's instance to snatch.

        Default: the most recently acquired non-sect instance. When
        legacy_type is given, filter by that type (still excluding sect).
        """
        instances = await self.db.ext.list_legacy_instances_by_owner(defender_id)
        for inst in instances:  # already newest-first
            if inst.legacy_type == "sect":
                continue
            if legacy_type and inst.legacy_type != legacy_type:
                continue
            return inst
        return None

    async def transfer_legacy(
        self, instance_id: int, new_owner: str
    ) -> LegacyInstance | None:
        """Transfer instance ownership to the snatch winner (single txn).

        Value and claimed tiers reset (winner must re-cultivate), the
        previous owner's activation is cleared, and the winner's activation
        is left untouched (they activate manually via 激活传承).
        """
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            instance = await self.db.ext.get_legacy_instance_by_id(instance_id)
            if not instance:
                await self.db.conn.rollback()
                return None
            await self.db.ext.clear_active_legacy_instance(
                instance.owner_id, instance_id, commit=False
            )
            instance.owner_id = new_owner
            instance.impart_value = 0
            instance.set_claimed_tiers([])
            instance.is_active = 0
            await self.db.ext.update_legacy_instance(instance, commit=False)
            await self.db.conn.commit()
            return instance
        except Exception:
            await self.db.conn.rollback()
            raise

    # ===== 失败冷却 / 被夺保护 =====

    async def can_challenge(
        self, challenger_id: str, target_id: str
    ) -> tuple[bool, int]:
        """Check the challenger's failure cooldown against the target.

        Returns:
            (allowed, remaining_seconds). remaining is 0 when allowed.
        """
        failed_at = await self.db.ext.get_impart_pk_cooldown(challenger_id, target_id)
        if failed_at is None:
            return True, 0
        elapsed = int(time.time()) - failed_at
        if elapsed >= IMPART_PK_COOLDOWN_SECONDS:
            return True, 0
        return False, IMPART_PK_COOLDOWN_SECONDS - elapsed

    async def record_challenge_failure(self, challenger_id: str, target_id: str):
        """Record a failed challenge (starts the 5-day per-target cooldown)."""
        await self.db.ext.upsert_impart_pk_cooldown(
            challenger_id, target_id, int(time.time())
        )

    async def get_snatch_protection_remaining(self, user_id: str) -> int:
        """Return remaining snatch-protection seconds for the player (0 if none)."""
        snatched_at = await self.db.ext.get_impart_snatch_protection(user_id)
        if snatched_at is None:
            return 0
        elapsed = int(time.time()) - snatched_at
        if elapsed >= IMPART_SNATCH_PROTECTION_SECONDS:
            return 0
        return IMPART_SNATCH_PROTECTION_SECONDS - elapsed

    async def record_snatch_protection(self, user_id: str, commit: bool = False):
        """Record that the player's legacy was just snatched (3-day protection)."""
        await self.db.ext.upsert_impart_snatch_protection(
            user_id, int(time.time()), commit=commit
        )

    # ===== 排行 =====

    async def get_ranking(self, limit: int = 10) -> list[dict]:
        """Rank players by total impart value across all instances."""
        return await self.db.ext.get_legacy_value_ranking(limit)

    # ===== 面板 =====

    def build_panel(self, instances: list[LegacyInstance]) -> str:
        """Build the Chinese info panel listing all held instances."""
        if not instances:
            return (
                "✨ 传承信息\n"
                "━━━━━━━━━━━━━━━\n"
                "你尚未持有任何传承。\n"
                "获取途径：宗门宝库领取 / 历练与秘境机缘触发\n"
                "（均需先战胜传承之地的守护者）"
            )

        lines = ["✨ 传承信息", "━━━━━━━━━━━━━━━"]
        active = next((i for i in instances if i.is_active), None)
        for inst in instances:
            name = self.get_type_name(inst.legacy_type)
            mark = "🌟激活中" if inst.is_active else "未激活"
            current_tier = self._calculate_tier(inst.legacy_type, inst.impart_value)
            tiers = self._get_tiers_config(inst.legacy_type)
            next_tier = next(
                (t for t in tiers if t.get("tier", 0) > current_tier), None
            )
            if next_tier:
                required = next_tier.get("impart_value_required", 0)
                progress = (
                    min(100, int(inst.impart_value / required * 100)) if required else 0
                )
                next_line = (
                    f"下一阶：第{next_tier['tier']}阶（需{required}，进度{progress}%）"
                )
            else:
                next_line = "已达最高等阶"
            claimed = inst.get_claimed_tiers()
            claimed_text = ", ".join(str(t) for t in claimed) if claimed else "无"
            lines.append(
                f"【{name}】#{inst.id}（{mark}）\n"
                f"  传承值：{inst.impart_value}｜当前等阶：第{current_tier}阶\n"
                f"  {next_line}｜已领取：{claimed_text}"
            )

        lines.append("━━━━━━━━━━━━━━━")
        if active is None:
            lines.append("⚠ 未激活传承，出关不会累积传承值。发送「激活传承」选择一条。")
        else:
            lines.append("出关时仅激活中的传承累积传承值（每15分钟+1点）。")
        return "\n".join(lines)

    # ===== 奖励发放 =====

    async def _grant_pending_rewards(
        self, player: Player, instance: LegacyInstance, commit: bool = True
    ) -> list[str]:
        """Grant all unclaimed tier rewards the instance has reached.

        Returns a list of Chinese reward messages for newly granted rewards.
        """
        tiers = self._get_tiers_config(instance.legacy_type)
        current_tier = self._calculate_tier(instance.legacy_type, instance.impart_value)
        claimed = set(instance.get_claimed_tiers())
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

        if claimed != set(instance.get_claimed_tiers()):
            instance.set_claimed_tiers(sorted(claimed))
            await self.db.ext.update_legacy_instance(instance, commit=commit)

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
            skill_cfg = self.config_manager.game_config.get("skill_system", {})
            max_star = skill_cfg.get("max_star", 3)
            compensation = int(
                skill_cfg.get("star_compensation_base", 1000)
                * skill_cfg.get("star_compensation_ratio", 0.5)
            )
            is_new, star = await self.db.ext.learn_or_star_up(
                player.user_id,
                skill_id,
                "impart",
                max_star=max_star,
                max_star_exp_compensation=compensation,
            )
            name = skill_def.get("name", skill_id)
            if is_new:
                return f"领悟传承功法【{name}】"
            if star >= max_star and compensation > 0:
                # 保持内存中的 player 同步：_grant_pending_rewards 随后会通过
                # update_player 落盘整行，不同步会覆盖掉本次补偿发放。
                player.experience += compensation
                return (
                    f"传承功法【{name}】已达{max_star}星圆满，"
                    f"传承所得折算为 {compensation} 点修为"
                )
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
