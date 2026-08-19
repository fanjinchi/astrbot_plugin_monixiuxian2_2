# managers/sect_manager.py
"""
宗门系统管理器 - 处理宗门创建、管理、捐献、任务等逻辑
参照NoneBot2插件的xiuxian_sect实现
"""

import json
import random
import time

from astrbot.api import logger

from ..data.data_manager import DataBase
from ..models_extended import Sect, UserStatus

SECT_NAME_MIN_LENGTH = 2
SECT_NAME_MAX_LENGTH = 12
SECT_NAME_FORBIDDEN = ["管理员", "系统", "官方", "GM", "admin"]

# 系统默认宗门的宗主占位值（默认宗门无宗主玩家）
SYSTEM_SECT_OWNER = ""


class SectManager:
    """宗门系统管理器"""

    def __init__(self, db: DataBase, config_manager=None):
        self.db = db
        self.config_manager = config_manager
        self.config = getattr(config_manager, "sect_config", None) or {}
        self.sect_factions = getattr(config_manager, "sect_factions", None) or {}
        self.sect_tasks = getattr(config_manager, "sect_tasks", None) or {}

    # ===== 职位配置辅助（唯一事实源：sect_config.json 的 positions） =====

    def _get_positions(self) -> dict:
        """Return the positions section of sect_config.json."""
        positions = self.config.get("positions")
        return positions if isinstance(positions, dict) else {}

    def get_position_name(self, position: int) -> str:
        """Return the configured display name of a position."""
        info = self._get_positions().get(str(position))
        return info.get("name", "未知") if isinstance(info, dict) else "未知"

    def get_position_permission(self, position: int) -> int:
        """Return the configured permission level of a position."""
        info = self._get_positions().get(str(position))
        if not isinstance(info, dict):
            return 0
        try:
            return int(info.get("permission", 0))
        except (TypeError, ValueError):
            return 0

    def _get_permission_ladder(self) -> list[int]:
        """Return distinct configured permission levels, sorted descending."""
        perms = set()
        for key in self._get_positions():
            try:
                perms.add(self.get_position_permission(int(key)))
            except (TypeError, ValueError):
                continue
        return sorted(perms, reverse=True)

    def get_entry_position(self) -> int:
        """Return the lowest-permission position id for new members (default 4)."""
        entry_position, entry_perm = 4, None
        for key, info in self._get_positions().items():
            if not isinstance(info, dict):
                continue
            try:
                position_id = int(key)
            except (TypeError, ValueError):
                continue
            perm = self.get_position_permission(position_id)
            if entry_perm is None or perm < entry_perm:
                entry_position, entry_perm = position_id, perm
        return entry_position

    def get_position_benefits(self, position: int) -> dict:
        """Return the configured benefits of a position.

        Always returns a dict with ``daily_stones`` / ``shop_discount`` /
        ``unlocks`` keys, falling back to safe defaults (no salary, no
        discount, no unlocks) when the position or its benefits are missing.
        """
        default = {"daily_stones": 0, "shop_discount": 1.0, "unlocks": []}
        info = self._get_positions().get(str(position))
        if not isinstance(info, dict):
            return default
        benefits = info.get("benefits")
        if not isinstance(benefits, dict):
            return default
        return {
            "daily_stones": int(benefits.get("daily_stones", 0) or 0),
            "shop_discount": float(benefits.get("shop_discount", 1.0) or 1.0),
            "unlocks": list(benefits.get("unlocks") or []),
        }

    # ===== 建筑配置（默认宗门读 faction buildings；玩家宗门读全局默认节） =====

    def get_sect_buildings(self, sect: Sect | None) -> dict:
        """Return the effective buildings config for a sect.

        System sects read their faction's ``buildings`` section; player-built
        sects fall back to the global default ``buildings`` section of
        sect_config.json. ``upgrade_cost[i]`` is the sect-materials cost of
        upgrading a building from level i to level i+1.
        """
        if sect is not None and sect.faction_id:
            faction = self._get_faction(sect.faction_id)
            if faction and isinstance(faction.get("buildings"), dict):
                return faction["buildings"]
        buildings = self.config.get("buildings")
        return buildings if isinstance(buildings, dict) else {}

    def _validate_sect_name(self, name: str) -> tuple[bool, str]:
        """验证宗门名称"""
        if len(name) < SECT_NAME_MIN_LENGTH or len(name) > SECT_NAME_MAX_LENGTH:
            return (
                False,
                f"❌ 宗门名称长度需在{SECT_NAME_MIN_LENGTH}-{SECT_NAME_MAX_LENGTH}字之间！",
            )
        for forbidden in SECT_NAME_FORBIDDEN:
            if forbidden.lower() in name.lower():
                return False, "❌ 宗门名称包含禁用词汇！"
        # 默认宗门名为系统保留，玩家建宗不得重名
        if name in self._get_system_sect_names():
            return False, f"❌ 『{name}』乃天下名门，不可用作宗门名称！"
        return True, ""

    def _get_system_sect_names(self) -> set[str]:
        """Collect configured default-sect names from sect_factions.json."""
        names = set()
        factions = (self.sect_factions or {}).get("factions", [])
        if not isinstance(factions, list):
            return names
        for faction in factions:
            if isinstance(faction, dict) and faction.get("name"):
                names.add(faction["name"])
        return names

    def _get_faction(self, faction_id: str | None) -> dict | None:
        """Look up a faction definition in sect_factions.json by id."""
        if not faction_id:
            return None
        factions = (self.sect_factions or {}).get("factions", [])
        if not isinstance(factions, list):
            return None
        for faction in factions:
            if isinstance(faction, dict) and faction.get("id") == faction_id:
                return faction
        return None

    async def ensure_system_sects(self):
        """Idempotently seed default system sects from sect_factions config.

        For each configured faction, look up the sects table by faction_id:
        create the sect when missing (is_system=1, no owner player), otherwise
        sync only text fields (name). Operational data (scale/materials/owner)
        is never overwritten, so re-running on every startup is safe.
        """
        factions = (self.sect_factions or {}).get("factions", [])
        if not isinstance(factions, list):
            return
        for faction in factions:
            if not isinstance(faction, dict):
                continue
            faction_id, name = faction.get("id"), faction.get("name")
            if not faction_id or not name:
                continue

            existing = await self.db.ext.get_sect_by_faction_id(faction_id)
            if existing:
                # 仅同步文案类字段，不覆盖运营数据
                if existing.sect_name != name:
                    existing.sect_name = name
                    await self.db.ext.update_sect(existing)
                    logger.info(f"【修仙插件】默认宗门「{name}」名称已同步。")
                continue

            # 兜底：配置名已被其他宗门占用时跳过创建，避免违反唯一约束
            name_clash = await self.db.ext.get_sect_by_name(name)
            if name_clash:
                logger.warning(
                    f"【修仙插件】默认宗门「{name}」(faction={faction_id}) 名称已被占用，跳过播种。"
                )
                continue

            mainbuff = faction.get("mainbuff") or []
            secbuff = faction.get("secbuff") or []
            new_sect = Sect(
                sect_id=0,  # 自动生成
                sect_name=name,
                sect_owner=SYSTEM_SECT_OWNER,
                sect_scale=faction.get("initial_scale", 100),
                sect_used_stone=0,
                sect_fairyland=0,
                sect_materials=faction.get("initial_materials", 100),
                # 镇派功法位从 faction 配置初始化（功法 id 列表，JSON 存储）
                mainbuff=json.dumps(mainbuff, ensure_ascii=False) if mainbuff else "0",
                secbuff=json.dumps(secbuff, ensure_ascii=False) if secbuff else "0",
                elixir_room_level=0,
                is_system=1,
                faction_id=faction_id,
            )
            await self.db.ext.create_sect(new_sect)
            logger.info(f"【修仙插件】已播种默认宗门「{name}」(faction={faction_id})。")

    async def reclaim_sect_treasures(self, user_id: str, sect_id: int) -> list[str]:
        """Reclaim sect treasures from a departing member.

        Items whose config entry is marked ``treasure: true`` and whose
        ``sect_id`` matches the sect's faction are reclaimed — both from the
        storage ring and from the weapon/armor equipment slots (equipped
        treasures are unequipped first). Personal items without sect
        attribution are not affected.

        Note: ``sect_bound`` skills/heart methods are deliberately NOT
        reclaimed or sealed here. Sect binding is an intrinsic property of
        the technique (non-transferable), and techniques already learned
        remain usable after leaving the sect (design D3 / spec「宗门绑定物
        归属与回收」).

        Args:
            user_id: Departing member's user ID.
            sect_id: The sect the member is leaving.

        Returns:
            Names of the reclaimed treasures (empty when nothing matched).
        """
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if not sect or not sect.faction_id:
            return []
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return []

        reclaimed = []
        changed = False

        # 已装备在武器/防具槽位的本宗宝物：先卸下再回收
        for slot in ("weapon", "armor"):
            equipped_name = getattr(player, slot, "")
            if not equipped_name:
                continue
            equipped_config = self._find_item_config(equipped_name)
            if (
                equipped_config
                and equipped_config.get("treasure")
                and equipped_config.get("sect_id") == sect.faction_id
            ):
                reclaimed.append(equipped_name)
                setattr(player, slot, "")
                changed = True

        items = player.get_storage_ring_items()
        for item_name in list(items.keys()):
            item_config = self._find_item_config(item_name)
            if (
                item_config
                and item_config.get("treasure")
                and item_config.get("sect_id") == sect.faction_id
            ):
                if item_name not in reclaimed:
                    reclaimed.append(item_name)
                del items[item_name]
                changed = True

        if changed:
            player.set_storage_ring_items(items)
            await self.db.update_player(player)
            logger.info(f"【修仙插件】玩家 {user_id} 离宗，回收宗门之宝: {reclaimed}")
        return reclaimed

    def _find_item_config(self, item_name: str) -> dict | None:
        """Find an item's config entry by name across item-like config tables."""
        if not self.config_manager:
            return None
        for source in (
            getattr(self.config_manager, "weapons_data", None),
            getattr(self.config_manager, "items_data", None),
            getattr(self.config_manager, "heart_methods_data", None),
            getattr(self.config_manager, "skills_data", None),
        ):
            if isinstance(source, dict):
                config = source.get(item_name)
                if isinstance(config, dict):
                    return config
        return None

    async def create_sect(
        self,
        user_id: str,
        sect_name: str,
        required_stone: int = None,
        required_level: int = None,
    ) -> tuple[bool, str]:
        """
        创建宗门

        Args:
            user_id: 用户ID
            sect_name: 宗门名称
            required_stone: 需求灵石（默认为配置值或10000）
            required_level: 需求境界等级（默认为配置值或3）

        Returns:
            (成功标志, 消息)
        """
        # 加载配置
        if required_stone is None:
            required_stone = self.config.get("create_cost", 10000)
        if required_level is None:
            required_level = self.config.get("create_level_required", 3)
        # 1. 检查用户是否存在
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        # 2. 检查是否已有宗门
        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门，无法创建新宗门！"

        # 3. 检查境界
        if player.level_index < required_level:
            return False, f"❌ 创建宗门需要达到境界等级 {required_level}！"

        # 4. 检查灵石
        if player.gold < required_stone:
            return False, f"❌ 创建宗门需要 {required_stone} 灵石！"

        # 验证宗门名称
        valid, error = self._validate_sect_name(sect_name)
        if not valid:
            return False, error

        # 5. 检查宗门名称是否重复
        existing_sect = await self.db.ext.get_sect_by_name(sect_name)
        if existing_sect:
            return False, f"❌ 宗门名称『{sect_name}』已被使用！"

        # 6. 扣除灵石
        player.gold -= required_stone
        await self.db.update_player(player)

        # 7. 创建宗门
        new_sect = Sect(
            sect_id=0,  # 自动生成
            sect_name=sect_name,
            sect_owner=user_id,
            sect_scale=100,  # 初始建设度
            sect_used_stone=0,
            sect_fairyland=0,
            sect_materials=100,  # 初始资材
            mainbuff="0",
            secbuff="0",
            elixir_room_level=0,
        )

        sect_id = await self.db.ext.create_sect(new_sect)

        # 8. 更新玩家宗门信息（设为宗主）
        await self.db.ext.update_player_sect_info(user_id, sect_id, 0)

        # 9. 初始化用户buff信息（如果没有）
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)

        return True, f"✨ 恭喜！你成功创建了宗门『{sect_name}』，成为一代宗主！"

    async def join_sect(self, user_id: str, sect_name: str) -> tuple[bool, str]:
        """
        加入宗门

        Args:
            user_id: 用户ID
            sect_name: 宗门名称

        Returns:
            (成功标志, 消息)
        """
        # 1. 检查用户
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        if player.sect_id != 0:
            return False, "❌ 你已经加入了宗门！请先退出当前宗门。"

        # 2. 查找宗门
        sect = await self.db.ext.get_sect_by_name(sect_name)
        if not sect:
            return False, f"❌ 未找到宗门『{sect_name}』！"

        entry_position = self.get_entry_position()

        # 3. 默认宗门（系统势力）校验入门境界区间；玩家宗门保持自由加入
        if sect.is_system:
            faction = self._get_faction(sect.faction_id)
            if faction is None:
                logger.warning(
                    f"【修仙插件】默认宗门「{sect.sect_name}」缺少 faction 配置"
                    f"（faction_id={sect.faction_id}），跳过入门境界校验。"
                )
            else:
                level_range = faction.get("join_level_range")
                if (
                    isinstance(level_range, list)
                    and len(level_range) == 2
                    and not (level_range[0] <= player.level_index <= level_range[1])
                ):
                    range_hint = self._format_level_range(level_range)
                    return False, (
                        f"❌ 『{sect_name}』不再招收此境界的修士！"
                        f"（招收范围：{range_hint}）"
                    )

        # 4. 加入宗门（默认从最低职阶做起）
        await self.db.ext.update_player_sect_info(user_id, sect.sect_id, entry_position)

        # 5. 初始化buff信息
        buff_info = await self.db.ext.get_buff_info(user_id)
        if not buff_info:
            await self.db.ext.create_buff_info(user_id)

        position_name = self.get_position_name(entry_position)
        if sect.is_system:
            return True, f"✨ 你成功拜入『{sect_name}』，成为{position_name}！"
        return True, f"✨ 你成功加入了宗门『{sect_name}』，成为{position_name}！"

    def _format_level_range(self, level_range: list) -> str:
        """Format a [min, max] level_index range as realm names for display."""

        def level_name(idx: int) -> str:
            if self.config_manager and hasattr(self.config_manager, "get_level_name"):
                name = self.config_manager.get_level_name(idx, "灵修")
                if name:
                    return name
            return f"境界{idx}"

        return f"{level_name(level_range[0])} ~ {level_name(level_range[1])}"

    async def leave_sect(self, user_id: str) -> tuple[bool, str]:
        """
        退出宗门

        Args:
            user_id: 用户ID

        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        if player.sect_id == 0:
            return False, "❌ 你还未加入任何宗门！"

        # 检查是否为宗主
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if sect and sect.sect_owner == user_id:
            return False, "❌ 宗主无法直接退出宗门！请先传位或解散宗门。"

        sect_name = sect.sect_name if sect else "未知宗门"

        # 回收宗门之宝（sect_bound 功法/心法为固有属性，离宗保留可用，不做处理）
        reclaimed = await self.reclaim_sect_treasures(user_id, player.sect_id)

        # 清除宗门信息
        await self.db.ext.update_player_sect_info(user_id, 0, self.get_entry_position())
        # 重新读取玩家，避免覆盖回收钩子写入的储物戒数据
        player = await self.db.get_player_by_id(user_id)
        if player:
            player.sect_contribution = 0
            await self.db.update_player(player)

        msg = f"✨ 你已退出宗门『{sect_name}』！"
        if reclaimed:
            msg += f"\n宗门之宝【{'、'.join(reclaimed)}】已归还宗门。"
        return True, msg

    async def donate_to_sect(self, user_id: str, stone_amount: int) -> tuple[bool, str]:
        """
        宗门捐献（建设度换算比率读 sect_config.json 的 scale_ratio）

        Args:
            user_id: 用户ID
            stone_amount: 捐献灵石数量

        Returns:
            (成功标志, 消息)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        if stone_amount <= 0:
            return False, "❌ 捐献数量必须大于0！"

        if player.gold < stone_amount:
            return False, f"❌ 你的灵石不足！当前拥有 {player.gold} 灵石。"

        scale_ratio = self.config.get("scale_ratio", 10)

        # 扣除灵石
        player.gold -= stone_amount

        # 增加宗门贡献度（1灵石 = 1贡献）
        player.sect_contribution += stone_amount
        await self.db.update_player(player)

        # 增加宗门建设度和灵石（1灵石 = scale_ratio 建设度）
        await self.db.ext.donate_to_sect(player.sect_id, stone_amount, scale_ratio)

        scale_gained = stone_amount * scale_ratio

        msg = f"✨ 捐献成功！消耗 {stone_amount} 灵石，宗门获得 {scale_gained} 建设度！\n你的宗门贡献度：{player.sect_contribution}"

        # 师承任务链：捐献阶段按灵石数量计数（失败不影响捐献主流程）
        try:
            master_msg = await self.advance_master_progress(
                user_id, "donate", stone_amount
            )
            if master_msg:
                msg += master_msg
        except Exception:
            logger.warning("【修仙插件】师承任务捐献进度推进失败", exc_info=True)

        return True, msg

    async def get_sect_info(self, user_id: str) -> tuple[bool, str, dict | None]:
        """
        获取宗门信息

        Args:
            user_id: 用户ID

        Returns:
            (成功标志, 消息, 宗门数据)
        """
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！", None

        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！", None

        # 获取宗主信息（默认宗门无宗主玩家）
        owner = await self.db.get_player_by_id(sect.sect_owner)
        if sect.is_system:
            owner_name = "无（掌门云游在外）"
        else:
            owner_name = (
                owner.user_name if owner and owner.user_name else sect.sect_owner
            )

        # 获取成员数量
        members = await self.db.ext.get_sect_members(sect.sect_id)
        member_count = len(members)

        # 构建信息
        position_name = self.get_position_name(player.sect_position)

        info_msg = f"""
🏛️ 宗门信息
━━━━━━━━━━━━━━━

宗门名称：{sect.sect_name}
宗主：{owner_name}
建设度：{sect.sect_scale}
宗门灵石：{sect.sect_used_stone}
宗门资材：{sect.sect_materials}
丹房等级：{sect.elixir_room_level}
成员数量：{member_count}人

你的职位：{position_name}
你的贡献：{player.sect_contribution}
        """.strip()

        sect_data = {
            "sect": sect,
            "player_position": player.sect_position,
            "player_contribution": player.sect_contribution,
            "member_count": member_count,
        }

        return True, info_msg, sect_data

    async def list_all_sects(self) -> tuple[bool, str]:
        """
        获取所有宗门列表

        Returns:
            (成功标志, 消息)
        """
        sects = await self.db.ext.get_all_sects()

        if not sects:
            return False, "❌ 当前还没有任何宗门！"

        msg = "🏛️ 宗门列表\n"
        msg += "━━━━━━━━━━━━━━━\n"

        for idx, sect in enumerate(sects[:10], 1):  # 只显示前10个
            owner = await self.db.get_player_by_id(sect.sect_owner)
            owner_name = owner.user_name if owner and owner.user_name else "未知"
            members = await self.db.ext.get_sect_members(sect.sect_id)

            msg += f"{idx}. 【{sect.sect_name}】\n"
            msg += f"   宗主：{owner_name}\n"
            msg += f"   建设度：{sect.sect_scale} | 成员：{len(members)}人\n\n"

        return True, msg

    async def change_position(
        self, operator_id: str, target_id: str, new_position: int
    ) -> tuple[bool, str]:
        """
        变更宗门职位

        Args:
            operator_id: 操作者ID（必须是宗主）
            target_id: 目标用户ID
            new_position: 新职位（0-4）

        Returns:
            (成功标志, 消息)
        """
        # 检查操作者
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        # 仅最高权限档（宗主）可变更职位
        ladder = self._get_permission_ladder()
        top_permission = ladder[0] if ladder else 0
        if self.get_position_permission(operator.sect_position) < top_permission:
            return False, "❌ 只有宗主才能变更职位！"

        # 检查目标用户
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"

        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"

        if target_id == operator_id:
            return False, "❌ 无法变更自己的职位！"

        positions = self._get_positions()
        if str(new_position) not in positions:
            valid = "、".join(
                f"{key}（{info.get('name', '?')}）"
                for key, info in sorted(positions.items(), key=lambda kv: str(kv[0]))
                if isinstance(info, dict)
            )
            return False, f"❌ 无效的职位！可选：{valid}"

        if new_position == 0:
            return False, "❌ 无法直接任命宗主！请使用传位功能。"

        # 变更职位
        await self.db.ext.update_player_sect_info(
            target_id, target.sect_id, new_position
        )

        target_name = target.user_name if target.user_name else target_id
        position_name = self.get_position_name(new_position)

        return True, f"✨ 已将 {target_name} 的职位变更为：{position_name}"

    async def transfer_ownership(
        self, current_owner_id: str, new_owner_id: str
    ) -> tuple[bool, str]:
        """
        宗主传位

        Args:
            current_owner_id: 当前宗主ID
            new_owner_id: 新宗主ID

        Returns:
            (成功标志, 消息)
        """
        # 检查当前宗主
        current_owner = await self.db.get_player_by_id(current_owner_id)
        if not current_owner or current_owner.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        sect = await self.db.ext.get_sect_by_id(current_owner.sect_id)
        if not sect or sect.sect_owner != current_owner_id:
            return False, "❌ 你不是宗主！"

        # 检查新宗主
        new_owner = await self.db.get_player_by_id(new_owner_id)
        if not new_owner:
            return False, "❌ 目标用户不存在！"

        if new_owner.sect_id != current_owner.sect_id:
            return False, "❌ 目标用户不在你的宗门！"

        if new_owner_id == current_owner_id:
            return False, "❌ 无法传位给自己！"

        # 执行传位
        sect.sect_owner = new_owner_id
        await self.db.ext.update_sect(sect)

        # 更新职位：新宗主->宗主，旧宗主->长老
        await self.db.ext.update_player_sect_info(new_owner_id, sect.sect_id, 0)
        await self.db.ext.update_player_sect_info(current_owner_id, sect.sect_id, 1)

        new_owner_name = new_owner.user_name if new_owner.user_name else new_owner_id

        return True, f"✨ 宗主之位已传给 {new_owner_name}！你现在是长老。"

    async def kick_member(self, operator_id: str, target_id: str) -> tuple[bool, str]:
        """
        踢出宗门成员

        Args:
            operator_id: 操作者ID
            target_id: 目标用户ID

        Returns:
            (成功标志, 消息)
        """
        # 检查操作者权限（权限档读 sect_config.json positions.permission）
        operator = await self.db.get_player_by_id(operator_id)
        if not operator or operator.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        ladder = self._get_permission_ladder()
        top_permission = ladder[0] if ladder else 0
        # 次高权限档（长老级）及以上才有踢人资格
        kick_threshold = ladder[1] if len(ladder) > 1 else top_permission
        lowest_permission = ladder[-1] if ladder else 0
        operator_perm = self.get_position_permission(operator.sect_position)

        if operator_perm < kick_threshold:
            return False, "❌ 只有宗主和长老才能踢出成员！"

        # 检查目标
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 目标用户不存在！"

        if target.sect_id != operator.sect_id:
            return False, "❌ 目标用户不在你的宗门！"

        if target_id == operator_id:
            return False, "❌ 无法踢出自己！"

        target_perm = self.get_position_permission(target.sect_position)

        # 非最高权限档（长老）只能踢最低权限档（外门弟子）
        if operator_perm < top_permission and target_perm > lowest_permission:
            return False, "❌ 长老只能踢出外门弟子！"

        # 无法踢出最高权限档（宗主）
        if target_perm >= top_permission:
            return False, "❌ 无法踢出宗主！"

        # 回收宗门之宝（sect_bound 功法/心法为固有属性，离宗保留可用）
        reclaimed = await self.reclaim_sect_treasures(target_id, target.sect_id)

        # 踢出
        target_name = target.user_name if target.user_name else target_id
        await self.db.ext.update_player_sect_info(
            target_id, 0, self.get_entry_position()
        )
        # 重新读取目标玩家，避免覆盖回收钩子写入的储物戒数据
        target = await self.db.get_player_by_id(target_id)
        if target:
            target.sect_contribution = 0
            await self.db.update_player(target)

        msg = f"✨ 已将 {target_name} 踢出宗门！"
        if reclaimed:
            msg += f"\n其持有的宗门之宝【{'、'.join(reclaimed)}】已归还宗门。"
        return True, msg

    async def perform_sect_task(self, user_id: str) -> tuple[bool, str]:
        """Execute a sect construction task drawn from the configured pool.

        A random task is drawn from ``sect_tasks.json`` ``construction_tasks``
        and settled by its ``cost``/``reward`` entries:
        - ``cost.stones``: deducted from the player's gold and donated to the
          sect (scale conversion follows the configured ``scale_ratio``).
        - ``cost.materials``: the player gathers materials for the sect,
          i.e. the sect's ``sect_materials`` increases by that amount.
        - ``reward.contribution`` / ``reward.exp``: granted to the player.

        The cooldown uses the task's own ``cooldown`` field (default 1h) and
        keeps the existing ``user_cd`` busy-state write (SECT_TASK type).
        The settlement section (deduct cost, grant rewards, bump counters,
        set cooldown) runs inside a single ``BEGIN IMMEDIATE`` transaction
        so a mid-settlement failure cannot charge the player without
        granting rewards.
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"

        tasks = (self.sect_tasks or {}).get("construction_tasks", [])
        if not isinstance(tasks, list) or not tasks:
            return False, "❌ 宗门暂无建设任务发布！"

        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)

        current_time = int(time.time())
        if (
            user_cd.type == UserStatus.SECT_TASK
            and current_time < user_cd.scheduled_time
        ):
            remaining = user_cd.scheduled_time - current_time
            return False, f"❌ 宗门任务冷却中！还需 {remaining // 60} 分钟。"

        task = random.choice(tasks)
        task_name = task.get("name", "建设任务")
        cost = task.get("cost", {}) if isinstance(task.get("cost"), dict) else {}
        reward = task.get("reward", {}) if isinstance(task.get("reward"), dict) else {}
        cooldown = int(task.get("cooldown", 3600) or 3600)
        scale_ratio = self.config.get("scale_ratio", 10)

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            # 灵石类任务前置校验（资材类任务由玩家外出采集，不消耗玩家货币）
            stones_cost = int(cost.get("stones", 0) or 0)
            if stones_cost > 0 and player.gold < stones_cost:
                await self.db.conn.rollback()
                return (
                    False,
                    f"❌ 灵石不足！建设任务【{task_name}】需捐献 {stones_cost} 灵石，"
                    f"你当前仅有 {player.gold} 灵石。",
                )

            lines = [f"✨ 完成建设任务【{task_name}】！"]

            if stones_cost > 0:
                player.gold -= stones_cost
                # 灵石入宗门库房并按 scale_ratio 折算建设度
                await self.db.ext.donate_to_sect(
                    player.sect_id, stones_cost, scale_ratio
                )
                lines.append(
                    f"捐献灵石：-{stones_cost}（宗门建设度 +{stones_cost * scale_ratio}）"
                )

            materials_gain = int(cost.get("materials", 0) or 0)
            if materials_gain > 0:
                # 玩家为宗门采集/筹备资材，资材直接入宗门库房
                await self.db.ext.update_sect_materials(
                    player.sect_id, materials_gain, 1
                )
                lines.append(f"宗门资材：+{materials_gain}")

            contribution_gain = int(reward.get("contribution", 0) or 0)
            if contribution_gain > 0:
                player.sect_contribution += contribution_gain
                lines.append(f"获得贡献：+{contribution_gain}")

            exp_gain = int(reward.get("exp", 0) or 0)
            if exp_gain > 0:
                player.experience += exp_gain
                lines.append(f"获得修为：+{exp_gain}")

            await self.db.update_player(player)
            await self.db.ext.increment_sect_task_count(user_id)

            # 冷却使用任务配置的 cooldown 字段，状态写法保持不变
            await self.db.ext.set_user_busy(
                user_id, UserStatus.SECT_TASK, current_time + cooldown
            )
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        return True, "\n".join(lines)

    async def handle_owner_death(
        self, sect_id: int, dead_owner_id: str
    ) -> tuple[bool, str]:
        """处理宗主死亡，自动传位或解散宗门"""
        members = await self.db.ext.get_sect_members(sect_id)
        # 过滤掉死亡的宗主
        remaining = [m for m in members if m.user_id != dead_owner_id]

        if not remaining:
            # 无其他成员，解散宗门
            await self.db.ext.delete_sect(sect_id)
            return True, "宗门已解散"

        # 按职位和贡献排序，选择新宗主
        remaining.sort(key=lambda m: (m.sect_position, -m.sect_contribution))
        new_owner = remaining[0]

        # 更新宗门宗主
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect:
            sect.sect_owner = new_owner.user_id
            await self.db.ext.update_sect(sect)
            await self.db.ext.update_player_sect_info(new_owner.user_id, sect_id, 0)

        return True, f"宗主之位已传给{new_owner.user_name or new_owner.user_id}"

    # ===== 4.1 洞天加成 =====

    async def get_fairyland_exp_bonus(self, player) -> tuple[float, int]:
        """Return the sect fairyland cultivation bonus for a player.

        Args:
            player: The player ending cultivation.

        Returns:
            ``(bonus_rate, fairyland_level)`` — ``bonus_rate`` equals
            ``exp_bonus_per_level * level`` from the effective buildings
            config; ``(0.0, 0)`` when the player has no sect or the sect has
            no fairyland.
        """
        if not player or not getattr(player, "sect_id", 0):
            return 0.0, 0
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect or sect.sect_fairyland <= 0:
            return 0.0, 0
        fairyland_cfg = self.get_sect_buildings(sect).get("fairyland", {})
        if not isinstance(fairyland_cfg, dict):
            return 0.0, sect.sect_fairyland
        try:
            per_level = float(fairyland_cfg.get("exp_bonus_per_level", 0) or 0)
        except (TypeError, ValueError):
            per_level = 0.0
        return per_level * sect.sect_fairyland, sect.sect_fairyland

    # ===== 4.2 丹房 =====

    def get_unlocked_elixir_pills(self, sect: Sect) -> list[str]:
        """Return the pill names unlocked at the sect's current elixir room level."""
        elixir_cfg = self.get_sect_buildings(sect).get("elixir_room", {})
        if not isinstance(elixir_cfg, dict):
            return []
        pills = elixir_cfg.get("unlock_pills_per_level", [])
        if not isinstance(pills, list):
            return []
        level = min(max(sect.elixir_room_level, 0), len(pills))
        return [str(p) for p in pills[:level]]

    def _pill_exists(self, pill_name: str) -> bool:
        """Check whether a pill name exists in any pill config table."""
        if not self.config_manager:
            return False
        for source in (
            getattr(self.config_manager, "exp_pills_data", None),
            getattr(self.config_manager, "pills_data", None),
            getattr(self.config_manager, "utility_pills_data", None),
        ):
            if isinstance(source, dict) and pill_name in source:
                return True
        return False

    async def get_elixir_room_status(self, user_id: str) -> tuple[bool, str]:
        """Show the player's sect elixir room level and daily claim status."""
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        elixir_cfg = self.get_sect_buildings(sect).get("elixir_room", {})
        max_level = (
            int(elixir_cfg.get("max_level", 0)) if isinstance(elixir_cfg, dict) else 0
        )
        unlocked = self.get_unlocked_elixir_pills(sect)
        claimed = bool(player.sect_elixir_get)

        lines = [
            f"🏯 【{sect.sect_name}】宗门丹房",
            "━━━━━━━━━━━━━━━",
            f"丹房等级：{sect.elixir_room_level}/{max_level}",
        ]
        if sect.elixir_room_level <= 0:
            lines.append("丹房尚未建成，暂无可领取的丹药。")
            lines.append("💡 可通过「宗门建设 丹房」升级丹房。")
        elif not unlocked:
            lines.append("当前等级未配置可领取的丹药。")
        else:
            lines.append(f"今日可领：{unlocked[-1]}（已解锁：{'、'.join(unlocked)}）")
            lines.append("领取状态：今日已领取" if claimed else "领取状态：今日未领取")
            if not claimed:
                lines.append("💡 发送「宗门丹房 领取」领取今日丹药。")
        return True, "\n".join(lines)

    async def claim_elixir(self, user_id: str) -> tuple[bool, str]:
        """Claim the daily elixir-room pill for the player's sect.

        The pill granted is the one unlocked at the sect's current elixir
        room level. The claim writes ``player.sect_elixir_get``; the flag is
        reset daily (wired at the check-in settlement point). The
        read-check-write critical section runs inside a ``BEGIN IMMEDIATE``
        transaction so concurrent claims cannot double-grant the pill.
        """
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(user_id)
            if not player or player.sect_id == 0:
                await self.db.conn.rollback()
                return False, "❌ 你还未加入宗门！"
            sect = await self.db.ext.get_sect_by_id(player.sect_id)
            if not sect:
                await self.db.conn.rollback()
                return False, "❌ 宗门信息异常！"

            if sect.elixir_room_level <= 0:
                await self.db.conn.rollback()
                return (
                    False,
                    "❌ 宗门丹房尚未建成！可通过「宗门建设 丹房」升级丹房。",
                )
            if player.sect_elixir_get:
                await self.db.conn.rollback()
                return False, "❌ 你今日已在丹房领取过丹药，请明日再来！"

            unlocked = self.get_unlocked_elixir_pills(sect)
            if not unlocked:
                await self.db.conn.rollback()
                return False, "❌ 丹房当前等级未配置可领取的丹药！"

            pill_name = unlocked[-1]
            if not self._pill_exists(pill_name):
                logger.warning(
                    f"【修仙插件】宗门「{sect.sect_name}」丹房配置的丹药「{pill_name}」不存在，领取失败。"
                )
                await self.db.conn.rollback()
                return False, f"❌ 丹房存丹【{pill_name}】的配置缺失，请联系管理员！"

            inventory = player.get_pills_inventory()
            inventory[pill_name] = inventory.get(pill_name, 0) + 1
            player.set_pills_inventory(inventory)
            player.sect_elixir_get = 1
            await self.db.update_player(player)

            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        return (
            True,
            f"🏯 你从宗门丹房领取了【{pill_name}】x1，已存入丹药背包！\n"
            f"（丹房 {sect.elixir_room_level} 级，每日可领取一次）",
        )

    # ===== 4.4 宗门建设 =====

    # 建筑中文名 -> buildings 配置键
    BUILDING_ALIASES = {
        "洞天": "fairyland",
        "洞天福地": "fairyland",
        "fairyland": "fairyland",
        "丹房": "elixir_room",
        "elixir_room": "elixir_room",
    }
    BUILDING_DISPLAY_NAMES = {"fairyland": "洞天", "elixir_room": "丹房"}

    async def get_construction_status(self, user_id: str) -> tuple[bool, str]:
        """Show the player's sect building status and upgrade costs."""
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        buildings = self.get_sect_buildings(sect)
        fairyland_cfg = (
            buildings.get("fairyland", {})
            if isinstance(buildings.get("fairyland"), dict)
            else {}
        )
        elixir_cfg = (
            buildings.get("elixir_room", {})
            if isinstance(buildings.get("elixir_room"), dict)
            else {}
        )

        lines = [
            f"🏗️ 【{sect.sect_name}】宗门建设",
            "━━━━━━━━━━━━━━━",
            f"建设度：{sect.sect_scale} | 宗门资材：{sect.sect_materials}",
        ]
        for key, level in (
            ("fairyland", sect.sect_fairyland),
            ("elixir_room", sect.elixir_room_level),
        ):
            cfg = fairyland_cfg if key == "fairyland" else elixir_cfg
            name = self.BUILDING_DISPLAY_NAMES[key]
            max_level = int(cfg.get("max_level", 0) or 0)
            effect = ""
            if key == "fairyland" and level > 0:
                per_level = float(cfg.get("exp_bonus_per_level", 0) or 0)
                effect = f"（全员闭关修为 +{per_level * level:.0%}）"
            if key == "elixir_room" and level > 0:
                unlocked = self.get_unlocked_elixir_pills(sect)
                if unlocked:
                    effect = f"（可领取：{'、'.join(unlocked)}）"
            cost_hint = self._format_upgrade_cost(cfg, level)
            lines.append(f"{name}：{level}/{max_level} 级{effect}{cost_hint}")

        mainbuff_names = self._format_buff_list(sect.get_mainbuff_list())
        lines.append(f"镇派功法：{mainbuff_names}")
        lines.append("💡 升级：「宗门建设 洞天」/「宗门建设 丹房」")
        return True, "\n".join(lines)

    def _format_upgrade_cost(self, cfg: dict, current_level: int) -> str:
        """Format the next-level upgrade cost hint for a building."""
        max_level = int(cfg.get("max_level", 0) or 0)
        if current_level >= max_level:
            return "（已满级）"
        costs = cfg.get("upgrade_cost", [])
        if not isinstance(costs, list) or current_level >= len(costs):
            return "（未配置升级消耗）"
        try:
            cost = int(costs[current_level])
        except (TypeError, ValueError):
            return "（未配置升级消耗）"
        return f"（升级需资材 {cost}）"

    def _format_buff_list(self, buff_ids: list) -> str:
        """Resolve buff slot skill IDs to display names."""
        if not buff_ids:
            return "未镶嵌"
        names = []
        for skill_id in buff_ids:
            skill = self._find_skill_by_ref(str(skill_id))
            names.append(skill.get("name", str(skill_id)) if skill else str(skill_id))
        return "、".join(names)

    async def upgrade_building(
        self, user_id: str, building_key: str
    ) -> tuple[bool, str]:
        """Upgrade a sect building (fairyland/elixir_room) by consuming materials.

        Cost is read from the building config ``upgrade_cost`` list (indexed
        by current level). System sects allow any member to upgrade;
        player-built sects require the second-highest permission tier
        (elder and above) to prevent griefing.
        The read-check-write critical section runs inside a
        ``BEGIN IMMEDIATE`` transaction so concurrent upgrades cannot
        double-spend sect materials.
        """
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(user_id)
            if not player or player.sect_id == 0:
                await self.db.conn.rollback()
                return False, "❌ 你还未加入宗门！"
            sect = await self.db.ext.get_sect_by_id(player.sect_id)
            if not sect:
                await self.db.conn.rollback()
                return False, "❌ 宗门信息异常！"

            key = self.BUILDING_ALIASES.get((building_key or "").strip())
            if not key:
                await self.db.conn.rollback()
                return False, "❌ 未知建筑！可升级：洞天、丹房（例如：宗门建设 洞天）"

            # 玩家宗门需长老及以上权限，防止低阶弟子擅动宗门资材
            if not sect.is_system:
                ladder = self._get_permission_ladder()
                threshold = (
                    ladder[1] if len(ladder) > 1 else (ladder[0] if ladder else 0)
                )
                if self.get_position_permission(player.sect_position) < threshold:
                    await self.db.conn.rollback()
                    return False, "❌ 只有宗主和长老才能主持宗门建设！"

            buildings = self.get_sect_buildings(sect)
            cfg = buildings.get(key, {})
            if not isinstance(cfg, dict) or not cfg:
                await self.db.conn.rollback()
                return False, "❌ 本宗门未配置该建筑！"

            current_level = (
                sect.sect_fairyland if key == "fairyland" else sect.elixir_room_level
            )
            max_level = int(cfg.get("max_level", 0) or 0)
            if current_level >= max_level:
                await self.db.conn.rollback()
                return (
                    False,
                    f"❌ {self.BUILDING_DISPLAY_NAMES[key]}已达满级（{max_level}级）！",
                )

            costs = cfg.get("upgrade_cost", [])
            if not isinstance(costs, list) or current_level >= len(costs):
                await self.db.conn.rollback()
                return False, "❌ 该建筑未配置升级消耗，无法升级！"
            try:
                cost = int(costs[current_level])
            except (TypeError, ValueError):
                await self.db.conn.rollback()
                return False, "❌ 该建筑升级消耗配置异常，无法升级！"

            if sect.sect_materials < cost:
                await self.db.conn.rollback()
                return (
                    False,
                    f"❌ 宗门资材不足！升级需 {cost} 资材，当前仅有 {sect.sect_materials}。"
                    f"\n💡 可通过「宗门任务」积累资材。",
                )

            sect.sect_materials -= cost
            if key == "fairyland":
                sect.sect_fairyland += 1
                new_level = sect.sect_fairyland
                per_level = float(cfg.get("exp_bonus_per_level", 0) or 0)
                effect_msg = f"全员闭关修为加成提升至 +{per_level * new_level:.0%}！"
            else:
                sect.elixir_room_level += 1
                new_level = sect.elixir_room_level
                unlocked = self.get_unlocked_elixir_pills(sect)
                effect_msg = (
                    f"丹房现可领取：{unlocked[-1]}！"
                    if unlocked
                    else "暂无新丹药解锁。"
                )
            await self.db.ext.update_sect(sect)

            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        name = self.BUILDING_DISPLAY_NAMES[key]
        return (
            True,
            f"🏗️ 【{sect.sect_name}】{name}升级成功！\n"
            f"消耗宗门资材：{cost}（剩余 {sect.sect_materials}）\n"
            f"{name}等级：{new_level}/{max_level}\n"
            f"{effect_msg}",
        )

    # ===== 4.3 镇派功法位 =====

    def _find_skill_by_ref(self, ref: str) -> dict | None:
        """Find a skill definition by ID or display name in skills.json."""
        skills_data = (
            getattr(self.config_manager, "skills_data", None)
            if self.config_manager
            else None
        )
        if not isinstance(skills_data, dict):
            return None
        for name, skill in skills_data.items():
            if isinstance(skill, dict) and (skill.get("id") == ref or name == ref):
                return skill
        return None

    async def manage_sect_buff(
        self, user_id: str, skill_ref: str = ""
    ) -> tuple[bool, str]:
        """View or set the sect's enshrined skill (mainbuff slot).

        Without an argument, shows the current mainbuff/secbuff skills.
        Setting is restricted to player-built sects (system sects are seeded
        from their faction config) and only the sect owner may change it;
        the skill reference (ID or name) must exist in skills.json.
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        if not skill_ref:
            mainbuff = self._format_buff_list(sect.get_mainbuff_list())
            secbuff = self._format_buff_list(sect.get_secbuff_list())
            return True, (
                f"🗡️ 【{sect.sect_name}】镇派功法\n"
                f"━━━━━━━━━━━━━━━\n"
                f"主镇派功法：{mainbuff}\n"
                f"辅镇派功法：{secbuff}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"镇派功法的触发技将加持全体弟子的战斗。\n"
                f"💡 宗主可用「镇派功法 <功法ID或名称>」更换主镇派功法。"
            )

        if sect.is_system:
            return False, "❌ 名门正派的镇派功法由祖师钦定，不可更改！"
        if sect.sect_owner != user_id:
            return False, "❌ 只有宗主才能镶嵌镇派功法！"

        skill = self._find_skill_by_ref(skill_ref.strip())
        if not skill:
            return False, f"❌ 未找到功法【{skill_ref}】！请核对功法ID或名称。"
        if not skill.get("trigger_skill"):
            return (
                False,
                f"❌ 功法【{skill.get('name', skill_ref)}】没有触发技，无法镇守宗门！",
            )

        sect.set_mainbuff_list([skill["id"]])
        await self.db.ext.update_sect(sect)
        return True, (
            f"🗡️ 【{skill.get('name', skill['id'])}】已镶嵌为本宗镇派功法！\n"
            f"其触发技【{skill['trigger_skill'].get('name', '未知')}】将加持全体弟子的战斗。"
        )

    # ===== 6.1 职阶晋升 =====

    async def promote_position(self, user_id: str) -> tuple[bool, str]:
        """Self-promote to the next position when both gates are met.

        The target is ``current_position - 1`` (lower number = higher rank);
        its ``promotion`` config defines the dual gates (contribution +
        level_index). Positions with ``promotion: null`` (e.g. 宗主) have no
        promotion channel — sect-master transfer logic is untouched. The
        read-check-write critical section runs inside a ``BEGIN IMMEDIATE``
        transaction.
        """
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(user_id)
            if not player or player.sect_id == 0:
                await self.db.conn.rollback()
                return False, "❌ 你还未加入宗门！"

            positions = self._get_positions()
            current = player.sect_position
            if current == 0:
                await self.db.conn.rollback()
                return False, "❌ 你已是一宗之主，无需晋升！"

            target = current - 1
            target_info = positions.get(str(target))
            if not isinstance(target_info, dict):
                await self.db.conn.rollback()
                return False, "❌ 你已是可晋升的最高职阶！"

            target_name = target_info.get("name", f"职位{target}")
            promotion = target_info.get("promotion")
            if not isinstance(promotion, dict):
                await self.db.conn.rollback()
                return (
                    False,
                    f"❌ 【{target_name}】之位不设晋升通道（宗主之位只能传位获得）！",
                )

            need_contribution = int(promotion.get("contribution", 0) or 0)
            need_level = int(promotion.get("level_index", 0) or 0)

            gaps = []
            if player.sect_contribution < need_contribution:
                gaps.append(
                    f"贡献不足（{player.sect_contribution}/{need_contribution}）"
                )
            if player.level_index < need_level:
                level_name = (
                    self.config_manager.get_level_name(
                        need_level, player.cultivation_type
                    )
                    if self.config_manager
                    and hasattr(self.config_manager, "get_level_name")
                    else f"境界{need_level}"
                )
                gaps.append(f"境界不足（需达到{level_name or f'境界{need_level}'}）")
            if gaps:
                await self.db.conn.rollback()
                return False, (
                    f"❌ 晋升【{target_name}】未达门槛：\n" + "\n".join(gaps)
                )

            await self.db.ext.update_player_sect_info(user_id, player.sect_id, target)
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        benefits = self.get_position_benefits(target)
        welfare_lines = []
        if benefits["daily_stones"] > 0:
            welfare_lines.append(f"每日签到俸禄：+{benefits['daily_stones']} 灵石")
        if benefits["shop_discount"] < 1.0:
            welfare_lines.append(f"商店折扣：{benefits['shop_discount'] * 10:g}折")
        if benefits["unlocks"]:
            welfare_lines.append(
                f"传承解锁：{'、'.join(str(u) for u in benefits['unlocks'])}"
            )
        welfare = (
            "\n".join(welfare_lines) if welfare_lines else "（该职阶暂无额外福利）"
        )

        return True, (
            f"🎖️ 晋升成功！你已成为【{target_name}】！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"职阶福利：\n{welfare}"
        )

    # ===== 6.2 宗门宝库（传承领取） =====

    def _find_item_config_by_id(self, item_id: str) -> dict | None:
        """Find an item-like config entry by its ``id`` field."""
        if not self.config_manager:
            return None
        for source in (
            getattr(self.config_manager, "weapons_data", None),
            getattr(self.config_manager, "items_data", None),
            getattr(self.config_manager, "heart_methods_data", None),
        ):
            if not isinstance(source, dict):
                continue
            for config in source.values():
                if isinstance(config, dict) and config.get("id") == item_id:
                    return config
        return None

    def _get_treasury_entries(self, sect: Sect) -> list[dict]:
        """Build the sect treasury listing from the faction config.

        Returns entries of ``{"kind": "treasure"|"heart_method", "id",
        "name", "min_position"}``. Player-built sects have no faction config
        and therefore an empty treasury.
        """
        faction = self._get_faction(sect.faction_id) if sect else None
        if not faction:
            return []
        entries = []
        for treasure in faction.get("treasures", []) or []:
            if not isinstance(treasure, dict) or not treasure.get("id"):
                continue
            config = self._find_item_config_by_id(treasure["id"])
            # None 哨兵：显式配置的 0（宗主即可领）必须保留，缺省才回退 99
            raw_min = treasure.get(
                "min_position", (config or {}).get("min_position", 99)
            )
            entries.append(
                {
                    "kind": "treasure",
                    "id": treasure["id"],
                    "name": (config or {}).get("name", treasure["id"]),
                    "min_position": 99 if raw_min is None else int(raw_min),
                }
            )
        for heart_id in faction.get("heart_methods", []) or []:
            config = self._find_item_config_by_id(str(heart_id))
            raw_min = (config or {}).get("min_position", 99)
            entries.append(
                {
                    "kind": "heart_method",
                    "id": str(heart_id),
                    "name": (config or {}).get("name", str(heart_id)),
                    "min_position": 99 if raw_min is None else int(raw_min),
                }
            )
        return entries

    def _can_claim_entry(self, entry: dict, position: int) -> bool:
        """Check claim eligibility: position gate or benefits.unlocks.

        ``min_position`` of 99 (the default when unconfigured) means "no
        position gate" — such entries are only claimable via
        ``benefits.unlocks``.
        """
        if entry["min_position"] < 99 and position <= entry["min_position"]:
            return True
        benefits = self.get_position_benefits(position)
        return entry["id"] in benefits["unlocks"]

    async def get_treasury_info(self, user_id: str) -> tuple[bool, str]:
        """Show the sect treasury: treasures/heart methods and requirements."""
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect:
            return False, "❌ 宗门信息异常！"

        entries = self._get_treasury_entries(sect)
        if not entries:
            return False, f"❌ 【{sect.sect_name}】宝库空空如也！"

        claims = player.get_sect_treasure_claims()
        lines = [
            f"🎁 【{sect.sect_name}】宗门宝库",
            "━━━━━━━━━━━━━━━",
            f"你的职阶：{self.get_position_name(player.sect_position)}",
        ]
        for entry in entries:
            kind_label = "镇派心法" if entry["kind"] == "heart_method" else "宗门之宝"
            gate = (
                f"{self.get_position_name(entry['min_position'])}及以上"
                if entry["min_position"] < 99
                else "职阶福利解锁"
            )
            status = (
                "（已领取）"
                if entry["id"] in claims
                else (
                    "（可领取）"
                    if self._can_claim_entry(entry, player.sect_position)
                    else ""
                )
            )
            lines.append(f"· 【{entry['name']}】{kind_label}｜需{gate}{status}")
        lines.append("💡 领取：「宗门宝库 <名称>」（宝物每人限领一次，离宗归还）")
        return True, "\n".join(lines)

    async def claim_treasure(self, user_id: str, item_ref: str) -> tuple[bool, str]:
        """Claim a treasury item (treasure to storage ring, heart method learned).

        Treasures are limited to one claim per person per item (recorded in
        ``player.sect_treasure_claims``) and are reclaimed on leaving the
        sect; heart methods can only be claimed by members who do not
        already own them. The read-check-write critical section runs inside
        a ``BEGIN IMMEDIATE`` transaction so concurrent claims cannot
        double-grant the same item.
        """
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            player = await self.db.get_player_by_id(user_id)
            if not player or player.sect_id == 0:
                await self.db.conn.rollback()
                return False, "❌ 你还未加入宗门！"
            sect = await self.db.ext.get_sect_by_id(player.sect_id)
            if not sect:
                await self.db.conn.rollback()
                return False, "❌ 宗门信息异常！"

            ref = (item_ref or "").strip()
            if not ref:
                await self.db.conn.rollback()
                return False, "❌ 请指定要领取的传承，例如：宗门宝库 青云镇山剑"

            entries = self._get_treasury_entries(sect)
            entry = next(
                (e for e in entries if e["id"] == ref or e["name"] == ref), None
            )
            if not entry:
                await self.db.conn.rollback()
                return False, f"❌ 宝库中没有【{ref}】！"

            if not self._can_claim_entry(entry, player.sect_position):
                gate = (
                    f"需{self.get_position_name(entry['min_position'])}及以上职阶"
                    if entry["min_position"] < 99
                    else "需职阶福利解锁"
                )
                await self.db.conn.rollback()
                return False, f"❌ 你的职阶不足以领取【{entry['name']}】（{gate}）！"

            claims = player.get_sect_treasure_claims()
            items = player.get_storage_ring_items()

            if entry["kind"] == "treasure":
                if entry["id"] in claims:
                    await self.db.conn.rollback()
                    return (
                        False,
                        f"❌ 你已领取过【{entry['name']}】，每件宗门之宝每人限领一次！",
                    )
            else:
                # 心法限未学者（储物戒持有或已装备均视为已习得）
                if entry["name"] in items or player.main_technique == entry["name"]:
                    await self.db.conn.rollback()
                    return False, f"❌ 你已习得【{entry['name']}】，无需重复领取！"
                if entry["id"] in claims:
                    await self.db.conn.rollback()
                    return False, f"❌ 你已领取过【{entry['name']}】！"

            items[entry["name"]] = items.get(entry["name"], 0) + 1
            player.set_storage_ring_items(items)
            claims.append(entry["id"])
            player.set_sect_treasure_claims(claims)
            await self.db.update_player(player)
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        if entry["kind"] == "treasure":
            return True, (
                f"🎁 你从宗门宝库领取了【{entry['name']}】，已存入储物戒！\n"
                f"⚠️ 宗门之宝仅授予使用权：不可赠予/交易，离宗时将自动归还宗门。"
            )
        return True, (
            f"🎁 你从宗门宝库领取了镇派心法【{entry['name']}】，已存入储物戒！\n"
            f"💡 使用「装备 {entry['name']}」即可主修此心法。"
        )

    # ===== 5. 师承任务链 =====

    # 阶段行为类型 -> 中文描述
    MASTER_TASK_TYPE_NAMES = {
        "win_pve": "历练/秘境战斗胜利",
        "adventure_complete": "完成历练",
        "breakthrough": "突破成功",
        "donate": "宗门捐献（灵石）",
    }

    def _get_master_chains(self, faction_id: str | None) -> list[dict]:
        """Return master task chains configured for a faction."""
        if not faction_id:
            return []
        chains = (self.sect_tasks or {}).get("master_task_chains", [])
        if not isinstance(chains, list):
            return []
        return [
            chain
            for chain in chains
            if isinstance(chain, dict) and chain.get("sect_id") == faction_id
        ]

    def _get_elder_name(self, faction: dict | None) -> str:
        """Return the first elder's name for master-task message signing."""
        elders = (faction or {}).get("elders") or []
        if elders and isinstance(elders[0], dict) and elders[0].get("name"):
            return str(elders[0]["name"])
        return "宗门长老"

    async def _resolve_master_context(self, user_id: str):
        """Load player/faction/chains for master task operations.

        Returns:
            ``(player, faction, chains)`` — player is None when the user does
            not exist; faction is None when the player is not in a system
            sect with a faction config; chains is the faction's chain list.
        """
        player = await self.db.get_player_by_id(user_id)
        if not player or player.sect_id == 0:
            return player, None, []
        sect = await self.db.ext.get_sect_by_id(player.sect_id)
        if not sect or not sect.is_system or not sect.faction_id:
            return player, None, []
        faction = self._get_faction(sect.faction_id)
        if not faction:
            return player, None, []
        return player, faction, self._get_master_chains(sect.faction_id)

    def _match_master_chain(
        self, player, chains: list[dict], progress: dict
    ) -> dict | None:
        """Pick the active chain: stored chain first, then level-range match.

        An unfinished chain stored on the player takes precedence over
        level-range matching, so a chain whose final stage is
        ``breakthrough`` can still settle after the breakthrough pushes the
        player out of the chain's ``level_range``. A finished chain is also
        returned so the view can render the completion state
        (``advance_master_progress`` guards on ``done``). Otherwise the
        first chain whose ``level_range`` contains the player's
        ``level_index`` wins.
        """

        def stages_of(chain: dict) -> list:
            stages = chain.get("stages")
            return stages if isinstance(stages, list) else []

        stored_id = progress.get("chain_id")
        if stored_id:
            # 进行中的链优先（突破可能把境界推出 level_range，链仍需可结算）；
            # 已完成的链也继续返回，以便查看指令展示"已全部完成"
            for chain in chains:
                if chain.get("id") == stored_id and stages_of(chain):
                    return chain
        for chain in chains:
            level_range = chain.get("level_range")
            if (
                isinstance(level_range, list)
                and len(level_range) == 2
                and level_range[0] <= player.level_index <= level_range[1]
                and stages_of(chain)
            ):
                return chain
        return None

    def _format_master_reward(self, reward: dict) -> str:
        """Format a stage reward dict as a Chinese preview string."""
        parts = []
        contribution = int(reward.get("contribution", 0) or 0)
        exp = int(reward.get("exp", 0) or 0)
        if contribution > 0:
            parts.append(f"贡献+{contribution}")
        if exp > 0:
            parts.append(f"修为+{exp}")
        if reward.get("skill_learn_chance"):
            parts.append("宗门功法领悟机会")
        return "、".join(parts) if parts else "无"

    async def get_master_task_status(self, user_id: str) -> tuple[bool, str]:
        """Show the player's master task chain with stage progress.

        View command for 「师承任务」: stages are listed in order with
        completion marks; the current stage shows its objective, progress
        (x/y) and a reward preview; the text is signed by the faction's
        first elder.
        """
        player, faction, chains = await self._resolve_master_context(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"
        if player.sect_id == 0:
            return False, "❌ 你还未加入宗门！"
        if not faction:
            return False, "❌ 师承任务仅名门大派设有传承，你所在的宗门暂无师承任务！"

        progress = player.get_sect_master_progress()
        chain = self._match_master_chain(player, chains, progress)
        if not chain:
            return False, "❌ 你当前的境界暂无对应的师承任务！"

        elder = self._get_elder_name(faction)
        stages = chain.get("stages", [])
        if progress.get("chain_id") == chain.get("id"):
            stage_index = int(progress.get("stage_index", 0) or 0)
            current_progress = int(progress.get("progress", 0) or 0)
            done = bool(progress.get("done"))
        else:
            stage_index, current_progress, done = 0, 0, False

        lines = [
            f"📜 师承任务 · {faction.get('name', '宗门')}",
            "━━━━━━━━━━━━━━━",
        ]
        if done:
            lines.append("🎓 师承任务已全部完成！")
            lines.append(f"—— {elder}")
            return True, "\n".join(lines)

        stage_index = min(stage_index, len(stages) - 1)
        for idx, stage in enumerate(stages):
            name = stage.get("name", f"第{idx + 1}阶段")
            if idx < stage_index:
                lines.append(f"✅ 【{name}】已完成")
            elif idx == stage_index:
                count = int(stage.get("count", 1) or 1)
                type_name = self.MASTER_TASK_TYPE_NAMES.get(
                    stage.get("type"), stage.get("type", "未知")
                )
                lines.append(f"▶ 【{name}】{type_name}：{current_progress}/{count}")
                if stage.get("text"):
                    lines.append(f"  {stage['text']}")
                reward = stage.get("reward")
                reward = reward if isinstance(reward, dict) else {}
                lines.append(f"  奖励：{self._format_master_reward(reward)}")
            else:
                lines.append(f"🔒 【{name}】未解锁")
        lines.append(f"—— {elder}")
        return True, "\n".join(lines)

    async def advance_master_progress(
        self, user_id: str, event_type: str, amount: int = 1
    ) -> str | None:
        """Advance the player's master task chain on a behavior event.

        Only advances when ``event_type`` matches the current stage's type;
        ``amount`` is the increment (1 for discrete events, the donated
        stone amount for ``donate``). Reaching the stage's ``count`` settles
        it: contribution/exp rewards are granted, a ``skill_learn_chance``
        reward draws one random skill from the named pool (learned via
        ``learn_or_star_up`` with sect attribution; max-star duplicates
        follow the existing exp-compensation rule), and the chain advances
        to the next stage (or completes). The skill is granted FIRST and
        the player row is then re-read before applying contribution/exp and
        stage progress, so the atomic max-star exp compensation inside
        ``learn_or_star_up`` is never overwritten by a stale full-row
        update; if the skill grant fails, the stage is NOT marked complete
        (stored progress is kept) so the next matching event retries the
        settlement.

        Args:
            user_id: Player user ID.
            event_type: Behavior event type (win_pve / adventure_complete /
                breakthrough / donate).
            amount: Progress increment (default 1).

        Returns:
            A user-visible message to append to the triggering action's
            reply, or None when nothing advanced. Callers MUST wrap this in
            try/except so a failure never breaks the main flow.
        """
        try:
            amount = max(1, int(amount))
        except (TypeError, ValueError):
            amount = 1

        player, faction, chains = await self._resolve_master_context(user_id)
        if not player or not faction or not chains:
            return None

        progress = player.get_sect_master_progress()
        chain = self._match_master_chain(player, chains, progress)
        if not chain:
            return None
        if progress.get("done") and progress.get("chain_id") == chain.get("id"):
            return None

        stages = chain.get("stages", [])
        if progress.get("chain_id") != chain.get("id"):
            progress = {"chain_id": chain["id"], "stage_index": 0, "progress": 0}
        stage_index = min(int(progress.get("stage_index", 0) or 0), len(stages) - 1)
        stage = stages[stage_index]
        if stage.get("type") != event_type:
            return None

        count = max(1, int(stage.get("count", 1) or 1))
        current = int(progress.get("progress", 0) or 0) + amount
        stage_name = stage.get("name", "师承任务")

        if current < count:
            player.set_sect_master_progress(
                {
                    "chain_id": chain["id"],
                    "stage_index": stage_index,
                    "progress": current,
                    "done": False,
                }
            )
            await self.db.update_player(player)
            return f"\n\n📜 师承任务【{stage_name}】进度：{current}/{count}"

        # ===== 阶段结算 =====
        elder = self._get_elder_name(faction)
        reward = stage.get("reward")
        reward = reward if isinstance(reward, dict) else {}
        reward_lines = []

        # 先发功法（内部 try/except，失败记日志并返回 None）：learn_or_star_up
        # 内部对满星折算修为做原子增量，必须在其完成后重新读取玩家再整行落库，
        # 否则折算修为会被旧值覆盖。功法发放失败时阶段不标记完成（进度保持），
        # 下次事件可重试结算。
        pool_name = reward.get("skill_learn_chance")
        if pool_name:
            skill_msg = await self._grant_master_skill(
                user_id, str(pool_name), faction.get("id")
            )
            if skill_msg:
                reward_lines.append(skill_msg)
            else:
                return (
                    f"\n\n⚠️ 师承任务【{stage_name}】的功法传承发放失败，"
                    "本次进度已保留，请再次触发对应行为重试结算。"
                )

        # 功法发放可能已原子写入折算修为，重新读取玩家避免整行覆盖
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return None

        contribution = int(reward.get("contribution", 0) or 0)
        if contribution > 0:
            player.sect_contribution += contribution
            reward_lines.append(f"宗门贡献 +{contribution}")
        exp_gain = int(reward.get("exp", 0) or 0)
        if exp_gain > 0:
            player.experience += exp_gain
            reward_lines.append(f"修为 +{exp_gain}")

        next_index = stage_index + 1
        finished = next_index >= len(stages)
        player.set_sect_master_progress(
            {
                "chain_id": chain["id"],
                "stage_index": stage_index if finished else next_index,
                "progress": 0,
                "done": finished,
            }
        )
        await self.db.update_player(player)

        lines = [f"📜 师承任务【{stage_name}】完成！"]
        if stage.get("text"):
            lines.append(stage["text"])
        lines.append(f"—— {elder}")
        if reward_lines:
            lines.append("奖励：" + "、".join(reward_lines))
        if finished:
            lines.append("🎓 师承任务已全部完成！")
        else:
            lines.append(f"下一阶段：【{stages[next_index].get('name', '?')}】")
        return "\n\n" + "\n".join(lines)

    async def _grant_master_skill(
        self, user_id: str, pool_name: str, faction_id: str | None
    ) -> str | None:
        """Draw one random skill from a sect pool and learn/star-up it.

        The skill is recorded with ``origin_sect_id`` / ``sect_bound``
        attribution. A duplicate at max star follows the existing max-star
        exp-compensation rule (same config keys as SkillManager). Database
        failures are caught and logged here; the method returns None so the
        caller keeps the stage unsettled and retries on the next event.
        """
        if not self.config_manager:
            return None
        skills_data = getattr(self.config_manager, "skills_data", None)
        if not isinstance(skills_data, dict):
            return None
        pool = [
            skill
            for skill in skills_data.values()
            if isinstance(skill, dict)
            and skill.get("_group") == pool_name
            and skill.get("id")
        ]
        if not pool:
            logger.warning(f"【修仙插件】师承任务功法池「{pool_name}」为空或不存在。")
            return None

        chosen = random.choice(pool)
        skill_id = str(chosen["id"])
        skill_name = chosen.get("name", skill_id)

        skill_cfg = {}
        game_config = getattr(self.config_manager, "game_config", None)
        if isinstance(game_config, dict):
            skill_cfg = game_config.get("skill_system", {}) or {}
        max_star = int(skill_cfg.get("max_star", 3) or 3)
        # 满星折算规则与 SkillManager._calc_star_compensation 一致
        compensation = int(
            skill_cfg.get("star_compensation_base", 1000)
            * skill_cfg.get("star_compensation_ratio", 0.5)
        )

        try:
            # learn_or_star_up 对"升到满星"与"已满星重复"都返回 (False, max_star)，
            # 需先记录调用前星级以区分：仅已满星重复才发放折算修为
            prev_star = await self.db.ext.get_star_level(user_id, skill_id)
            was_learned = await self.db.ext.is_skill_learned(user_id, skill_id)

            is_new, star_level = await self.db.ext.learn_or_star_up(
                user_id,
                skill_id,
                "master_task",
                max_star=max_star,
                max_star_exp_compensation=compensation,
                origin_sect_id=faction_id,
                sect_bound=True,
            )
        except Exception:
            logger.warning(
                f"【修仙插件】师承任务功法「{skill_name}」（{skill_id}）发放失败",
                exc_info=True,
            )
            return None
        if is_new:
            return f"领悟宗门功法【{skill_name}】"
        if was_learned and prev_star >= max_star and compensation > 0:
            return f"【{skill_name}】已达{max_star}星圆满，参悟折算修为 +{compensation}"
        return f"【{skill_name}】升至 {star_level} 星"
