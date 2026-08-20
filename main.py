import asyncio
from functools import wraps
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from .config_manager import ConfigManager
from .data import DataBase, MigrationManager
from .handlers import (
    AdventureHandlers,
    AlchemyHandlers,
    BankHandlers,
    BlessedLandHandlers,
    BossHandlers,
    BountyHandlers,
    BreakthroughHandler,
    CombatHandlers,
    DualCultivationHandlers,
    EquipmentHandler,
    GMHandler,
    ImpartHandlers,
    ImpartPkHandlers,
    MiscHandler,
    NicknameHandler,
    PillHandler,
    PlayerHandler,
    RankingHandlers,
    RiftHandlers,
    SectHandlers,
    ShopHandler,
    SpiritEyeHandlers,
    SpiritFarmHandlers,
    StorageRingHandler,
    TechniqueHandler,
)
from .managers import (
    AdventureManager,
    AlchemyManager,
    BankManager,
    BlessedLandManager,
    BossManager,
    BountyManager,
    CombatManager,
    DualCultivationManager,
    EnemyManager,
    ImpartManager,
    ImpartPkManager,
    PVECombatManager,
    RankingManager,
    RiftManager,
    SectManager,
    SpiritEyeManager,
    SpiritFarmManager,
)


def require_whitelist(func):
    """装饰器：检查群聊白名单权限"""

    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        """Block non-whitelisted group chats with an access-denied message, then run the command handler."""
        if not self._check_access(event):
            await self._send_access_denied_message(event)
            return
        async for result in func(self, event, *args, **kwargs):
            yield result

    return wrapper


# 指令定义
CMD_HELP = "修仙帮助"
CMD_START_XIUXIAN = "我要修仙"
CMD_PLAYER_INFO = "我的信息"
CMD_START_CULTIVATION = "闭关"
CMD_END_CULTIVATION = "出关"
CMD_CHECK_IN = "签到"
CMD_SHOW_EQUIPMENT = "我的装备"
CMD_EQUIP_ITEM = "装备"
CMD_UNEQUIP_ITEM = "卸下"
CMD_BREAKTHROUGH = "突破"
CMD_BREAKTHROUGH_INFO = "突破信息"
CMD_USE_PILL = "服用丹药"
CMD_SHOW_PILLS = "丹药背包"
CMD_PILL_INFO = "丹药信息"
CMD_PILL_PAVILION = "丹阁"
CMD_WEAPON_PAVILION = "器阁"
CMD_TREASURE_PAVILION = "百宝阁"
CMD_ITEM_INFO = "物品信息"
CMD_BUY = "购买"
CMD_STORAGE_RING = "储物戒"
CMD_STORE_ITEM = "存入"
CMD_RETRIEVE_ITEM = "取出"
CMD_UPGRADE_RING = "更换储物戒"
CMD_DISCARD_ITEM = "丢弃"
CMD_GIFT_ITEM = "赠予"
CMD_ACCEPT_GIFT = "接收"
CMD_REJECT_GIFT = "拒绝"
CMD_SEARCH_ITEM = "搜索物品"
CMD_RETRIEVE_ALL = "取出所有"

# 功法/修习目标指令
CMD_SET_STUDY_TARGET = "修习目标"
CMD_SHOW_STUDY_TARGET = "我的修习"
CMD_CLEAR_STUDY_TARGET = "取消修习"
CMD_SET_BATTLE_REPORT_COUNT = "战报条数"
CMD_ACTIVATE_TECHNIQUE = "激活功法"
CMD_DEACTIVATE_TECHNIQUE = "卸下功法"
CMD_MY_SKILLS = "我的技能"

# 宗门系统指令（统一入口：/宗门 <子命令>，子命令路由见 sect_handlers.handle_sect_entry）
CMD_SECT = "宗门"

# Boss系统指令
CMD_BOSS_INFO = "世界Boss"
CMD_BOSS_FIGHT = "挑战Boss"
CMD_SPAWN_BOSS = "生成Boss"

# 排行榜指令
CMD_RANK_LEVEL = "境界排行"
CMD_RANK_POWER = "战力排行"
CMD_RANK_WEALTH = "灵石排行"
CMD_RANK_DEPOSIT = "存款排行"

# 战斗指令
CMD_DUEL = "决斗"
CMD_SPAR = "切磋"

# 秘境系统指令
CMD_RIFT_LIST = "秘境列表"
CMD_RIFT_EXPLORE = "探索秘境"
CMD_RIFT_COMPLETE = "完成探索"
CMD_RIFT_EXIT = "退出秘境"

# 历练系统指令
CMD_ADVENTURE_START = "开始历练"
CMD_ADVENTURE_COMPLETE = "完成历练"
CMD_ADVENTURE_STATUS = "历练状态"
CMD_ADVENTURE_INFO = "历练信息"

# 炼丹系统指令
CMD_ALCHEMY_RECIPES = "丹药配方"
CMD_ALCHEMY_CRAFT = "炼丹"

# 传承系统指令
CMD_IMPART_INFO = "传承信息"

# Phase 1: 道号系统
CMD_CHANGE_NICKNAME = "改道号"

# Phase 2: 灵石银行
CMD_BANK_INFO = "银行"
CMD_BANK_DEPOSIT = "存灵石"
CMD_BANK_WITHDRAW = "取灵石"
CMD_BANK_INTEREST = "领取利息"
CMD_BANK_LOAN = "贷款"
CMD_BANK_REPAY = "还款"
CMD_BANK_TRANSACTIONS = "银行流水"
CMD_BANK_BREAKTHROUGH_LOAN = "突破贷款"

# Phase 2: 悬赏令
CMD_BOUNTY_LIST = "悬赏令"
CMD_BOUNTY_ACCEPT = "接取悬赏"
CMD_BOUNTY_STATUS = "悬赏状态"
CMD_BOUNTY_COMPLETE = "完成悬赏"
CMD_BOUNTY_ABANDON = "放弃悬赏"

# Phase 3: 传承PK
CMD_IMPART_CHALLENGE = "传承挑战"
CMD_IMPART_RANKING = "传承排行"

# Phase 4: 洞天福地
CMD_BLESSED_LAND_INFO = "我的洞天"
CMD_BLESSED_LAND_BUY = "购买洞天"
CMD_BLESSED_LAND_UPGRADE = "升级洞天"
CMD_BLESSED_LAND_COLLECT = "洞天收取"

# Phase 4: 灵田
CMD_SPIRIT_FARM_INFO = "我的灵田"
CMD_SPIRIT_FARM_CREATE = "开垦灵田"
CMD_SPIRIT_FARM_PLANT = "种植"
CMD_SPIRIT_FARM_HARVEST = "收获"
CMD_SPIRIT_FARM_UPGRADE = "升级灵田"

# Phase 4: 双修
CMD_DUAL_CULT_REQUEST = "双修"
CMD_DUAL_CULT_ACCEPT = "接受双修"
CMD_DUAL_CULT_REJECT = "拒绝双修"

# Phase 4: 灵眼
CMD_SPIRIT_EYE_INFO = "灵眼信息"
CMD_SPIRIT_EYE_CLAIM = "抢占灵眼"
CMD_SPIRIT_EYE_COLLECT = "灵眼收取"
CMD_SPIRIT_EYE_RELEASE = "释放灵眼"

CMD_REBIRTH = "弃道重修"

# GM 系统指令
CMD_GM = "修仙GM"
CMD_GM_HELP = "修仙GM帮助"


class XiuXianPlugin(Star):
    """修仙插件 - 文字修仙游戏"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        _current_dir = Path(__file__).parent
        self.config_manager = ConfigManager(_current_dir)

        files_config = self.config.get("FILES", {})
        db_filename = files_config.get("DATABASE_FILE", "xiuxian_data_v2.db")
        plugin_data_path = StarTools.get_data_dir("astrbot_plugin_monixiuxian2")
        plugin_data_path.mkdir(parents=True, exist_ok=True)
        db_path = plugin_data_path / db_filename
        self.db = DataBase(str(db_path))

        # 初始化核心管理器（需在业务处理器之前）
        from .core import (
            EquipmentManager,
            GMManager,
            SkillManager,
            StorageRingManager,
        )

        self.skill_manager = SkillManager(self.config_manager, self.db)
        self.storage_ring_mgr = StorageRingManager(self.db, self.config_manager)
        self.equipment_mgr = EquipmentManager(
            self.db, self.config_manager, self.storage_ring_mgr
        )
        # 宗门管理器提前初始化（player_handler 弃道重修路径依赖其回收钩子）
        self.sect_mgr = SectManager(self.db, self.config_manager)

        self.misc_handler = MiscHandler(self.db)
        self.player_handler = PlayerHandler(
            self.db,
            self.config,
            self.config_manager,
            self.skill_manager,
            sect_mgr=self.sect_mgr,
        )
        self.equipment_handler = EquipmentHandler(
            self.db, self.config_manager, self.skill_manager
        )
        self.breakthrough_handler = BreakthroughHandler(
            self.db,
            self.config_manager,
            self.config,
            self.skill_manager,
            sect_manager=self.sect_mgr,
        )
        self.pill_handler = PillHandler(self.db, self.config_manager)
        self.shop_handler = ShopHandler(self.db, self.config, self.config_manager)
        self.storage_ring_handler = StorageRingHandler(self.db, self.config_manager)

        # Phase 2: 灵石银行和悬赏令（GMManager 依赖 bounty_mgr，需提前初始化）
        self.bank_mgr = BankManager(self.db, self.config)
        self.bounty_mgr = BountyManager(self.db, self.storage_ring_mgr)

        self.combat_mgr = CombatManager(self.config_manager, self.skill_manager)
        self.enemy_mgr = EnemyManager(config_manager=self.config_manager)
        self.impart_mgr = ImpartManager(self.db, self.config_manager)
        self.pve_combat_mgr = PVECombatManager(
            self.combat_mgr,
            self.enemy_mgr,
            self.config_manager,
            self.impart_mgr,
        )
        self.boss_mgr = BossManager(
            self.db,
            self.combat_mgr,
            self.config_manager,
            self.storage_ring_mgr,
        )
        self.rift_mgr = RiftManager(
            self.db, self.config_manager, self.storage_ring_mgr, self.pve_combat_mgr
        )
        self.rank_mgr = RankingManager(self.db, self.combat_mgr, self.config_manager)
        self.adventure_mgr = AdventureManager(
            self.db, self.storage_ring_mgr, self.pve_combat_mgr
        )
        self.alchemy_mgr = AlchemyManager(
            self.db, self.config_manager, self.storage_ring_mgr
        )

        # 初始化 GM 管理器（依赖前面创建的管理器）
        self.gm_manager = GMManager(
            self.db,
            self.config_manager,
            self.storage_ring_mgr,
            self.equipment_mgr,
            self.adventure_mgr,
            self.rift_mgr,
            self.boss_mgr,
            bounty_manager=self.bounty_mgr,
            plugin_data_path=plugin_data_path,
            broadcast_callback=self._broadcast_boss_spawn,
            sect_manager=self.sect_mgr,
        )

        # 初始化新功能处理器
        # ranking_handlers 在其后构造，统一入口分发器需要排行路由，故构造后回填
        self.sect_handlers = SectHandlers(self.db, self.sect_mgr, self.bounty_mgr)
        self.boss_handlers = BossHandlers(self.db, self.boss_mgr)
        self.combat_handlers = CombatHandlers(
            self.db, self.combat_mgr, self.config_manager
        )
        self.technique_handler = TechniqueHandler(
            self.db, self.config_manager, self.skill_manager, self.storage_ring_mgr
        )
        self.ranking_handlers = RankingHandlers(self.db, self.rank_mgr)
        self.sect_handlers.ranking_handlers = self.ranking_handlers
        self.rift_handlers = RiftHandlers(self.db, self.rift_mgr)
        self.adventure_handlers = AdventureHandlers(self.db, self.adventure_mgr)
        self.alchemy_handlers = AlchemyHandlers(self.db, self.alchemy_mgr)
        self.impart_handlers = ImpartHandlers(self.db, self.impart_mgr)
        self.nickname_handler = NicknameHandler(self.db)  # Phase 1
        self.gm_handler = GMHandler(self.db, self.gm_manager)

        self.bank_handlers = BankHandlers(self.db, self.bank_mgr)
        self.bounty_handlers = BountyHandlers(self.db, self.bounty_mgr)

        # Phase 3: 传承PK
        self.impart_pk_mgr = ImpartPkManager(self.db, self.combat_mgr, self.impart_mgr)
        self.impart_pk_handlers = ImpartPkHandlers(self.db, self.impart_pk_mgr)

        # Phase 4: 扩展功能
        self.blessed_land_mgr = BlessedLandManager(self.db)
        self.blessed_land_handlers = BlessedLandHandlers(self.db, self.blessed_land_mgr)
        self.spirit_farm_mgr = SpiritFarmManager(self.db, self.storage_ring_mgr)
        self.spirit_farm_handlers = SpiritFarmHandlers(self.db, self.spirit_farm_mgr)
        self.dual_cult_mgr = DualCultivationManager(
            self.db, self.config, self.config_manager
        )
        self.dual_cult_handlers = DualCultivationHandlers(self.db, self.dual_cult_mgr)
        self.spirit_eye_mgr = SpiritEyeManager(self.db)
        self.spirit_eye_handlers = SpiritEyeHandlers(self.db, self.spirit_eye_mgr)

        self.boss_task = None  # Boss生成任务
        self.loan_check_task = None  # 贷款逾期检查任务
        self.spirit_eye_task = None  # 灵眼生成任务
        self.bounty_check_task = None  # 悬赏过期检查任务

        access_control_config = self.config.get("ACCESS_CONTROL", {})
        self.whitelist_groups = [
            str(g) for g in access_control_config.get("WHITELIST_GROUPS", [])
        ]
        self.boss_admins = [
            str(a) for a in access_control_config.get("BOSS_ADMINS", [])
        ]
        self.gm_admins = [str(a) for a in access_control_config.get("GM_ADMINS", [])]

        logger.info(f"【修仙插件】XiuXianPlugin 初始化完成，数据库路径: {db_path}")

    def _check_access(self, event: AstrMessageEvent) -> bool:
        """检查访问权限，支持群聊白名单控制"""
        # 如果没有配置白名单，允许所有访问
        if not self.whitelist_groups:
            return True

        # 获取群组ID，私聊时为None
        group_id = event.get_group_id()

        # 如果是私聊，允许访问
        if not group_id:
            return True

        # 检查群组是否在白名单中
        if str(group_id) in self.whitelist_groups:
            return True

        return False

    def _check_boss_admin(self, event: AstrMessageEvent) -> bool:
        """检查是否为Boss管理员"""
        if not self.boss_admins:
            return False
        sender_id = str(event.get_sender_id())
        return sender_id in self.boss_admins

    def _check_gm_admin(self, event: AstrMessageEvent) -> bool:
        """检查是否为GM管理员"""
        if not self.gm_admins:
            return False
        sender_id = str(event.get_sender_id())
        return sender_id in self.gm_admins

    def _is_boss_enabled(self) -> bool:
        """Return whether the world-boss feature is enabled."""
        if not self.config_manager:
            return True
        return self.config_manager.game_config.get("boss", {}).get("enabled", True)

    def _is_pve_enabled(self) -> bool:
        """Return whether the PvE rift feature is enabled."""
        if not self.config_manager:
            return True
        return self.config_manager.game_config.get("pve", {}).get("enabled", True)

    async def _send_access_denied_message(self, event: AstrMessageEvent):
        """发送访问被拒绝的提示消息"""
        try:
            await event.send("抱歉，此群聊未在修仙插件的白名单中，无法使用相关功能。")
        except Exception:
            # 如果发送失败，静默处理
            pass

    async def initialize(self):
        """Plugin startup hook: connect the database, run migrations, and launch scheduled tasks.

        Starts the Boss spawn, loan overdue check, spirit eye spawn, and bounty
        expiry loops (Boss loop skipped when disabled in config). Called once by
        AstrBot after the plugin is (re)loaded.
        """
        await self.db.connect()
        migration_manager = MigrationManager(self.db.conn, self.config_manager)
        await migration_manager.migrate()

        # 播种默认宗门（幂等 upsert，失败不阻断插件加载）
        try:
            await self.sect_mgr.ensure_system_sects()
        except Exception as e:
            logger.error("【修仙插件】默认宗门播种失败: %s", e, exc_info=True)

        # 启动定时任务
        if self._is_boss_enabled():
            self.boss_task = asyncio.create_task(self._schedule_boss_spawn())
        else:
            logger.info("【修仙插件】世界Boss玩法已关闭，跳过Boss生成定时任务。")
        self.loan_check_task = asyncio.create_task(self._schedule_loan_check())
        self.spirit_eye_task = asyncio.create_task(self._schedule_spirit_eye_spawn())
        self.bounty_check_task = asyncio.create_task(self._schedule_bounty_check())

        logger.info("【修仙插件】已加载。")

    async def terminate(self):
        """Plugin shutdown hook: cancel all scheduled background tasks."""
        if self.boss_task:
            self.boss_task.cancel()
        if self.loan_check_task:
            self.loan_check_task.cancel()
        if self.spirit_eye_task:
            self.spirit_eye_task.cancel()
        if self.bounty_check_task:
            self.bounty_check_task.cancel()
        await self.db.close()
        logger.info("【修仙插件】已卸载。")

    async def _schedule_boss_spawn(self):
        """Boss定时生成任务（支持持久化和指数退避）"""
        import time

        retry_count = 0
        max_retry_delay = 3600

        while True:
            try:
                await self.db.ensure_connection()
                interval = self.config_manager.boss_config.get("spawn_interval", 3600)

                # 检查是否有存储的下次刷新时间
                next_spawn_str = await self.db.ext.get_system_config(
                    "boss_next_spawn_time"
                )
                current_time = int(time.time())

                if next_spawn_str:
                    next_spawn_time = int(next_spawn_str)
                    remaining = next_spawn_time - current_time
                    if remaining > 0:
                        logger.info(f"【修仙插件】Boss将在 {remaining} 秒后刷新")
                        await asyncio.sleep(remaining)
                else:
                    next_spawn_time = current_time + interval
                    await self.db.ext.set_system_config(
                        "boss_next_spawn_time", str(next_spawn_time)
                    )
                    await asyncio.sleep(interval)

                # 尝试生成Boss
                if self.boss_mgr:
                    success, msg, boss = await self.boss_mgr.auto_spawn_boss()
                    if success and boss:
                        logger.info(f"【修仙插件】自动生成Boss: {boss.boss_name}")
                        await self._broadcast_boss_spawn(boss)

                # 设置下次刷新时间
                next_spawn_time = int(time.time()) + interval
                await self.db.ext.set_system_config(
                    "boss_next_spawn_time", str(next_spawn_time)
                )

                # 成功后重置重试计数
                retry_count = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Boss生成任务异常: {e}")
                retry_count += 1
                delay = min(60 * (2**retry_count), max_retry_delay)
                logger.info(
                    f"【修仙插件】Boss任务将在 {delay} 秒后重试（第{retry_count}次）"
                )
                await asyncio.sleep(delay)

    async def _broadcast_boss_spawn(self, boss):
        """广播Boss刷新消息到所有白名单群聊"""
        from astrbot.api.event import MessageChain

        if not self.whitelist_groups:
            logger.debug("【修仙插件】未配置白名单群聊，跳过Boss广播")
            return

        # 构建广播消息
        broadcast_msg = (
            f"👹 世界Boss降临！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"名称：{boss.boss_name}\n"
            f"境界：{boss.boss_level}\n"
            f"血量：{boss.hp}/{boss.max_hp}\n"
            f"攻击：{boss.atk}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 击败奖励：{boss.stone_reward} 灵石\n"
            f"⚔️ 发送「挑战Boss」参与讨伐！"
        )

        message_chain = MessageChain().message(broadcast_msg)

        # 获取所有平台实例
        try:
            platforms = self.context.platform_manager.get_insts()
            for platform in platforms:
                platform_name = (
                    platform.meta().name
                    if hasattr(platform, "meta") and callable(platform.meta)
                    else "unknown"
                )
                for group_id in self.whitelist_groups:
                    # 构建 unified_msg_origin: platform_name:message_type:session_id
                    umo = f"{platform_name}:GroupMessage:{group_id}"
                    try:
                        await self.context.send_message(umo, message_chain)
                        logger.debug(f"【修仙插件】Boss广播已发送到群 {group_id}")
                    except Exception as e:
                        logger.warning(
                            f"【修仙插件】Boss广播发送失败 (群{group_id}): {e}"
                        )
        except Exception as e:
            logger.error(f"【修仙插件】Boss广播异常: {e}")

    async def _broadcast_boss_defeat(self, player_name: str, battle_result: dict):
        """广播Boss被击杀消息到所有白名单群聊"""
        from astrbot.api.event import MessageChain

        if not self.whitelist_groups:
            return

        reward = battle_result.get("reward", 0)
        rounds = battle_result.get("rounds", 0)

        broadcast_msg = (
            f"🎉 世界Boss已被击杀！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"击杀者：{player_name}\n"
            f"战斗回合：{rounds}\n"
            f"获得奖励：{reward} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"恭喜大侠！下一只Boss即将刷新..."
        )

        message_chain = MessageChain().message(broadcast_msg)

        try:
            platforms = self.context.platform_manager.get_insts()
            for platform in platforms:
                platform_name = (
                    platform.meta().name
                    if hasattr(platform, "meta") and callable(platform.meta)
                    else "unknown"
                )
                for group_id in self.whitelist_groups:
                    umo = f"{platform_name}:GroupMessage:{group_id}"
                    try:
                        await self.context.send_message(umo, message_chain)
                    except Exception as e:
                        logger.warning(
                            f"【修仙插件】Boss击杀广播发送失败 (群{group_id}): {e}"
                        )
        except Exception as e:
            logger.error(f"【修仙插件】Boss击杀广播异常: {e}")

    async def _schedule_loan_check(self):
        """贷款逾期检查定时任务（每小时检查一次，支持指数退避）"""

        retry_count = 0
        max_retry_delay = 3600

        while True:
            try:
                await self.db.ensure_connection()
                # 每小时检查一次逾期贷款
                await asyncio.sleep(3600)

                # 处理逾期贷款
                processed = await self.bank_mgr.check_and_process_overdue_loans()

                if processed:
                    logger.info(f"【修仙插件】处理了 {len(processed)} 笔逾期贷款")
                    # 广播逾期玩家被追杀的消息
                    for loan_info in processed:
                        if loan_info.get("death"):
                            await self._broadcast_loan_death(loan_info)

                # 成功后重置重试计数
                retry_count = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"贷款检查任务异常: {e}")
                retry_count += 1
                delay = min(60 * (2**retry_count), max_retry_delay)
                logger.info(
                    f"【修仙插件】贷款检查任务将在 {delay} 秒后重试（第{retry_count}次）"
                )
                await asyncio.sleep(delay)

    async def _broadcast_loan_death(self, loan_info: dict):
        """广播贷款逾期玩家被追杀的消息"""
        from astrbot.api.event import MessageChain

        if not self.whitelist_groups:
            return

        player_name = loan_info.get("player_name", "某修士")
        principal = loan_info.get("principal", 0)

        broadcast_msg = (
            f"💀 银行追杀公告 💀\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修士【{player_name}】因贷款逾期未还\n"
            f"欠款：{principal:,} 灵石\n"
            f"已被灵石银行追杀致死！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 借贷有风险，还款需及时！"
        )

        message_chain = MessageChain().message(broadcast_msg)

        try:
            platforms = self.context.platform_manager.get_insts()
            for platform in platforms:
                platform_name = (
                    platform.meta().name
                    if hasattr(platform, "meta") and callable(platform.meta)
                    else "unknown"
                )
                for group_id in self.whitelist_groups:
                    umo = f"{platform_name}:GroupMessage:{group_id}"
                    try:
                        await self.context.send_message(umo, message_chain)
                    except Exception as e:
                        logger.warning(
                            f"【修仙插件】贷款追杀广播发送失败 (群{group_id}): {e}"
                        )
        except Exception as e:
            logger.error(f"【修仙插件】贷款追杀广播异常: {e}")

    async def _schedule_spirit_eye_spawn(self):
        """灵眼生成定时任务（每2小时生成一个，支持指数退避）"""
        import time

        retry_count = 0
        max_retry_delay = 3600

        while True:
            try:
                await self.db.ensure_connection()
                # 每2小时生成一个灵眼
                spawn_interval = 7200

                # 检查是否有存储的下次刷新时间
                next_spawn_str = await self.db.ext.get_system_config(
                    "spirit_eye_next_spawn_time"
                )
                current_time = int(time.time())

                if next_spawn_str:
                    next_spawn_time = int(next_spawn_str)
                    remaining = next_spawn_time - current_time
                    if remaining > 0:
                        logger.info(f"【修仙插件】灵眼将在 {remaining} 秒后刷新")
                        await asyncio.sleep(remaining)
                else:
                    next_spawn_time = current_time + spawn_interval
                    await self.db.ext.set_system_config(
                        "spirit_eye_next_spawn_time", str(next_spawn_time)
                    )
                    await asyncio.sleep(spawn_interval)

                # 生成灵眼
                success, msg = await self.spirit_eye_mgr.spawn_spirit_eye()
                if success:
                    logger.info(f"【修仙插件】{msg}")
                    await self._broadcast_spirit_eye_spawn(msg)

                # 设置下次刷新时间
                next_spawn_time = int(time.time()) + spawn_interval
                await self.db.ext.set_system_config(
                    "spirit_eye_next_spawn_time", str(next_spawn_time)
                )

                # 成功后重置重试计数
                retry_count = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"灵眼生成任务异常: {e}")
                retry_count += 1
                delay = min(60 * (2**retry_count), max_retry_delay)
                logger.info(
                    f"【修仙插件】灵眼任务将在 {delay} 秒后重试（第{retry_count}次）"
                )
                await asyncio.sleep(delay)

    async def _schedule_bounty_check(self):
        """悬赏过期检查定时任务（每30分钟检查一次）"""
        while True:
            try:
                await self.db.ensure_connection()
                await asyncio.sleep(1800)  # 30分钟
                expired = await self.bounty_mgr.check_and_expire_bounties()
                if expired > 0:
                    logger.info(f"【修仙插件】处理了 {expired} 个过期悬赏任务")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"悬赏检查任务异常: {e}")
                await asyncio.sleep(60)

    async def _broadcast_spirit_eye_spawn(self, msg: str):
        """广播灵眼刷新消息"""
        from astrbot.api.event import MessageChain

        if not self.whitelist_groups:
            return

        broadcast_msg = f"👁️ {msg}\n💡 使用 /灵眼信息 查看详情"
        message_chain = MessageChain().message(broadcast_msg)

        try:
            platforms = self.context.platform_manager.get_insts()
            for platform in platforms:
                platform_name = (
                    platform.meta().name
                    if hasattr(platform, "meta") and callable(platform.meta)
                    else "unknown"
                )
                for group_id in self.whitelist_groups:
                    umo = f"{platform_name}:GroupMessage:{group_id}"
                    try:
                        await self.context.send_message(umo, message_chain)
                    except Exception as e:
                        logger.warning(
                            f"【修仙插件】灵眼广播发送失败 (群{group_id}): {e}"
                        )
        except Exception as e:
            logger.error(f"【修仙插件】灵眼广播异常: {e}")

    @filter.command(CMD_HELP, "显示帮助信息")
    @require_whitelist
    async def handle_help(self, event: AstrMessageEvent):
        """Command 「修仙帮助」- 显示帮助信息; routes to misc_handler.handle_help."""
        async for r in self.misc_handler.handle_help(event):
            yield r

    @filter.command(CMD_START_XIUXIAN, "开始你的修仙之路")
    @require_whitelist
    async def handle_start_xiuxian(
        self, event: AstrMessageEvent, cultivation_type: str = ""
    ):
        """Command 「我要修仙」- 开始你的修仙之路; routes to player_handler.handle_start_xiuxian."""
        async for r in self.player_handler.handle_start_xiuxian(
            event, cultivation_type
        ):
            yield r

    @filter.command(CMD_PLAYER_INFO, "查看你的角色信息")
    @require_whitelist
    async def handle_player_info(self, event: AstrMessageEvent):
        """Command 「我的信息」- 查看你的角色信息; routes to player_handler.handle_player_info."""
        async for r in self.player_handler.handle_player_info(event):
            yield r

    @filter.command(CMD_REBIRTH, "弃道重修（7天一次）")
    @require_whitelist
    async def handle_rebirth(self, event: AstrMessageEvent, confirm: str = ""):
        """Command 「弃道重修」- 弃道重修（7天一次）; routes to player_handler.handle_rebirth."""
        async for r in self.player_handler.handle_rebirth(event, confirm):
            yield r

    @filter.command(CMD_START_CULTIVATION, "开始闭关修炼")
    @require_whitelist
    async def handle_start_cultivation(self, event: AstrMessageEvent):
        """Command 「闭关」- 开始闭关修炼; routes to player_handler.handle_start_cultivation."""
        async for r in self.player_handler.handle_start_cultivation(event):
            yield r

    @filter.command(CMD_END_CULTIVATION, "结束闭关修炼")
    @require_whitelist
    async def handle_end_cultivation(self, event: AstrMessageEvent):
        """Command 「出关」- 结束闭关修炼; routes to player_handler.handle_end_cultivation."""
        async for r in self.player_handler.handle_end_cultivation(event):
            yield r

    @filter.command(CMD_CHECK_IN, "每日签到领取灵石")
    @require_whitelist
    async def handle_check_in(self, event: AstrMessageEvent):
        """Command 「签到」- 每日签到领取灵石; routes to player_handler.handle_check_in."""
        async for r in self.player_handler.handle_check_in(event):
            yield r

    @filter.command(CMD_SHOW_EQUIPMENT, "查看已装备的物品")
    @require_whitelist
    async def handle_show_equipment(self, event: AstrMessageEvent):
        """Command 「我的装备」- 查看已装备的物品; routes to equipment_handler.handle_show_equipment."""
        async for r in self.equipment_handler.handle_show_equipment(event):
            yield r

    @filter.command(CMD_EQUIP_ITEM, "装备物品")
    @require_whitelist
    async def handle_equip_item(self, event: AstrMessageEvent, item_name: str = ""):
        """Command 「装备」- 装备物品; routes to equipment_handler.handle_equip_item."""
        async for r in self.equipment_handler.handle_equip_item(event, item_name):
            yield r

    @filter.command(CMD_UNEQUIP_ITEM, "卸下装备")
    @require_whitelist
    async def handle_unequip_item(
        self, event: AstrMessageEvent, slot_or_name: str = ""
    ):
        """Command 「卸下」- 卸下装备; routes to equipment_handler.handle_unequip_item."""
        async for r in self.equipment_handler.handle_unequip_item(event, slot_or_name):
            yield r

    @filter.command(CMD_BREAKTHROUGH_INFO, "查看突破信息")
    @require_whitelist
    async def handle_breakthrough_info(self, event: AstrMessageEvent):
        """Command 「突破信息」- 查看突破信息; routes to breakthrough_handler.handle_breakthrough_info."""
        async for r in self.breakthrough_handler.handle_breakthrough_info(event):
            yield r

    @filter.command(CMD_BREAKTHROUGH, "尝试突破境界")
    @require_whitelist
    async def handle_breakthrough(self, event: AstrMessageEvent, pill_name: str = ""):
        """Command 「突破」- 尝试突破境界; routes to breakthrough_handler.handle_breakthrough."""
        async for r in self.breakthrough_handler.handle_breakthrough(event, pill_name):
            yield r

    # 功法/修习目标指令
    @filter.command(CMD_SET_STUDY_TARGET, "将已拥有的功法设为修习目标")
    @require_whitelist
    async def handle_set_study_target(
        self, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Command 「修习目标」- 将已拥有的功法设为修习目标; routes to technique_handler.handle_set_study_target."""
        async for r in self.technique_handler.handle_set_study_target(
            event, skill_name
        ):
            yield r

    @filter.command(CMD_SHOW_STUDY_TARGET, "查看当前修习目标")
    @require_whitelist
    async def handle_show_study_target(self, event: AstrMessageEvent):
        """Command 「我的修习」- 查看当前修习目标; routes to technique_handler.handle_show_study_target."""
        async for r in self.technique_handler.handle_show_study_target(event):
            yield r

    @filter.command(CMD_CLEAR_STUDY_TARGET, "取消当前修习目标")
    @require_whitelist
    async def handle_clear_study_target(self, event: AstrMessageEvent):
        """Command 「取消修习」- 取消当前修习目标; routes to technique_handler.handle_clear_study_target."""
        async for r in self.technique_handler.handle_clear_study_target(event):
            yield r

    @filter.command(CMD_SET_BATTLE_REPORT_COUNT, "设置战报合并条数（1-50）")
    @require_whitelist
    async def handle_set_battle_report_count(
        self, event: AstrMessageEvent, count: str = ""
    ):
        """Command 「战报条数」- 设置战报合并条数（1-50）; routes to technique_handler.handle_set_battle_report_count."""
        async for r in self.technique_handler.handle_set_battle_report_count(
            event, count
        ):
            yield r

    @filter.command(CMD_ACTIVATE_TECHNIQUE, "激活已领悟的功法")
    @require_whitelist
    async def handle_activate_technique(
        self, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Command 「激活功法」- 激活已领悟的功法; routes to technique_handler.handle_activate_technique."""
        async for r in self.technique_handler.handle_activate_technique(
            event, skill_name
        ):
            yield r

    @filter.command(CMD_DEACTIVATE_TECHNIQUE, "卸下已激活的功法")
    @require_whitelist
    async def handle_deactivate_technique(
        self, event: AstrMessageEvent, skill_name: str = ""
    ):
        """Command 「卸下功法」- 卸下已激活的功法; routes to technique_handler.handle_deactivate_technique."""
        async for r in self.technique_handler.handle_deactivate_technique(
            event, skill_name
        ):
            yield r

    @filter.command(CMD_MY_SKILLS, "查看我的功法")
    @require_whitelist
    async def handle_my_skills(self, event: AstrMessageEvent):
        """Command 「我的技能」- 查看我的功法; routes to technique_handler.handle_my_skills."""
        async for r in self.technique_handler.handle_my_skills(event):
            yield r

    @filter.command(CMD_USE_PILL, "服用丹药")
    @require_whitelist
    async def handle_use_pill(self, event: AstrMessageEvent, pill_name: str = ""):
        """Command 「服用丹药」- 服用丹药; routes to pill_handler.handle_use_pill."""
        async for r in self.pill_handler.handle_use_pill(event, pill_name):
            yield r

    @filter.command(CMD_SHOW_PILLS, "查看丹药背包")
    @require_whitelist
    async def handle_show_pills(self, event: AstrMessageEvent):
        """Command 「丹药背包」- 查看丹药背包; routes to pill_handler.handle_show_pills."""
        async for r in self.pill_handler.handle_show_pills(event):
            yield r

    @filter.command(CMD_PILL_INFO, "查看丹药信息")
    @require_whitelist
    async def handle_pill_info(self, event: AstrMessageEvent, pill_name: str = ""):
        """Command 「丹药信息」- 查看丹药信息; routes to pill_handler.handle_pill_info."""
        async for r in self.pill_handler.handle_pill_info(event, pill_name):
            yield r

    @filter.command(CMD_PILL_PAVILION, "查看丹阁丹药")
    @require_whitelist
    async def handle_pill_pavilion(self, event: AstrMessageEvent):
        """Command 「丹阁」- 查看丹阁丹药; routes to shop_handler.handle_pill_pavilion."""
        async for r in self.shop_handler.handle_pill_pavilion(event):
            yield r

    @filter.command(CMD_WEAPON_PAVILION, "查看器阁武器")
    @require_whitelist
    async def handle_weapon_pavilion(self, event: AstrMessageEvent):
        """Command 「器阁」- 查看器阁武器; routes to shop_handler.handle_weapon_pavilion."""
        async for r in self.shop_handler.handle_weapon_pavilion(event):
            yield r

    @filter.command(CMD_TREASURE_PAVILION, "查看百宝阁物品")
    @require_whitelist
    async def handle_treasure_pavilion(self, event: AstrMessageEvent):
        """Command 「百宝阁」- 查看百宝阁物品; routes to shop_handler.handle_treasure_pavilion."""
        async for r in self.shop_handler.handle_treasure_pavilion(event):
            yield r

    @filter.command(CMD_ITEM_INFO, "查看物品详细效果")
    @require_whitelist
    async def handle_item_info(self, event: AstrMessageEvent, item_name: str = ""):
        """Command 「物品信息」- 查看物品详细效果; routes to shop_handler.handle_item_info."""
        async for r in self.shop_handler.handle_item_info(event, item_name):
            yield r

    @filter.command(CMD_BUY, "购买物品")
    @require_whitelist
    async def handle_buy(self, event: AstrMessageEvent, item_name: str = ""):
        """Command 「购买」- 购买物品; routes to shop_handler.handle_buy."""
        async for r in self.shop_handler.handle_buy(event, item_name):
            yield r

    @filter.command(CMD_STORAGE_RING, "查看储物戒信息")
    @require_whitelist
    async def handle_storage_ring(self, event: AstrMessageEvent):
        """Command 「储物戒」- 查看储物戒信息; routes to storage_ring_handler.handle_storage_ring."""
        async for r in self.storage_ring_handler.handle_storage_ring(event):
            yield r

    @filter.command(CMD_STORE_ITEM, "存入物品到储物戒")
    @require_whitelist
    async def handle_store_item(self, event: AstrMessageEvent, args: str = ""):
        """Command 「存入」- 存入物品到储物戒; routes to storage_ring_handler.handle_store_item."""
        async for r in self.storage_ring_handler.handle_store_item(event, args):
            yield r

    @filter.command(CMD_RETRIEVE_ITEM, "从储物戒取出物品")
    @require_whitelist
    async def handle_retrieve_item(self, event: AstrMessageEvent, args: str = ""):
        """Command 「取出」- 从储物戒取出物品; routes to storage_ring_handler.handle_retrieve_item."""
        async for r in self.storage_ring_handler.handle_retrieve_item(event, args):
            yield r

    @filter.command(CMD_UPGRADE_RING, "升级储物戒")
    @require_whitelist
    async def handle_upgrade_ring(self, event: AstrMessageEvent, ring_name: str = ""):
        """Command 「更换储物戒」- 升级储物戒; routes to storage_ring_handler.handle_upgrade_ring."""
        async for r in self.storage_ring_handler.handle_upgrade_ring(event, ring_name):
            yield r

    @filter.command(CMD_DISCARD_ITEM, "丢弃储物戒中的物品")
    @require_whitelist
    async def handle_discard_item(self, event: AstrMessageEvent, args: str = ""):
        """Command 「丢弃」- 丢弃储物戒中的物品; routes to storage_ring_handler.handle_discard_item."""
        async for r in self.storage_ring_handler.handle_discard_item(event, args):
            yield r

    @filter.command(CMD_GIFT_ITEM, "赠予物品给其他玩家")
    @require_whitelist
    async def handle_gift_item(self, event: AstrMessageEvent, args: str = ""):
        """Command 「赠予」- 赠予物品给其他玩家; routes to storage_ring_handler.handle_gift_item."""
        async for r in self.storage_ring_handler.handle_gift_item(event, args):
            yield r

    @filter.command(CMD_ACCEPT_GIFT, "接收赠予的物品")
    @require_whitelist
    async def handle_accept_gift(self, event: AstrMessageEvent):
        """Command 「接收」- 接收赠予的物品; routes to storage_ring_handler.handle_accept_gift."""
        async for r in self.storage_ring_handler.handle_accept_gift(event):
            yield r

    @filter.command(CMD_REJECT_GIFT, "拒绝赠予的物品")
    @require_whitelist
    async def handle_reject_gift(self, event: AstrMessageEvent):
        """Command 「拒绝」- 拒绝赠予的物品; routes to storage_ring_handler.handle_reject_gift."""
        async for r in self.storage_ring_handler.handle_reject_gift(event):
            yield r

    @filter.command(CMD_SEARCH_ITEM, "搜索储物戒物品")
    @require_whitelist
    async def handle_search_item(self, event: AstrMessageEvent, keyword: str = ""):
        """Command 「搜索物品」- 搜索储物戒物品; routes to storage_ring_handler.handle_search_item."""
        async for r in self.storage_ring_handler.handle_search_item(event, keyword):
            yield r

    @filter.command(CMD_RETRIEVE_ALL, "批量取出物品")
    @require_whitelist
    async def handle_retrieve_all(self, event: AstrMessageEvent, category: str = ""):
        """Command 「取出所有」- 批量取出物品; routes to storage_ring_handler.handle_retrieve_all."""
        async for r in self.storage_ring_handler.handle_retrieve_all(event, category):
            yield r

    # ===== 宗门系统指令（统一入口） =====

    @filter.command(CMD_SECT, "宗门统一入口")
    @require_whitelist
    async def handle_sect(self, event: AstrMessageEvent):
        """Command 「宗门」- 宗门统一入口，子命令路由（创建/加入/悬赏/商店等）; routes to sect_handlers.handle_sect_entry."""
        async for r in self.sect_handlers.handle_sect_entry(event):
            yield r

    # ===== Boss系统指令 =====

    @filter.command(CMD_BOSS_INFO, "查看世界Boss状态")
    @require_whitelist
    async def handle_boss_info(self, event: AstrMessageEvent):
        """Command 「世界Boss」- 查看世界Boss状态; routes to boss_handlers.handle_boss_info."""
        if not self._is_boss_enabled():
            yield event.plain_result("🛠️ 世界Boss玩法正在维护中，敬请期待！")
            return
        async for r in self.boss_handlers.handle_boss_info(event):
            yield r

    @filter.command(CMD_BOSS_FIGHT, "挑战世界Boss")
    @require_whitelist
    async def handle_boss_fight(self, event: AstrMessageEvent):
        """Command 「挑战Boss」- 挑战世界Boss; routes to boss_handlers.handle_boss_fight."""
        if not self._is_boss_enabled():
            yield event.plain_result("🛠️ 世界Boss玩法正在维护中，敬请期待！")
            return
        user_id = event.get_sender_id()
        success, msg, battle_result = await self.boss_handlers.handle_boss_fight(
            user_id
        )
        yield event.plain_result(msg)

        if success and battle_result and battle_result.get("winner") == user_id:
            player = await self.db.get_player_by_id(user_id)
            player_name = (
                player.user_name
                if player and player.user_name
                else f"道友{str(user_id)[:6]}"
            )
            await self._broadcast_boss_defeat(player_name, battle_result)

    @filter.command(CMD_SPAWN_BOSS, "生成世界Boss(管理员)")
    @require_whitelist
    async def handle_spawn_boss(self, event: AstrMessageEvent):
        """Command 「生成Boss」- 生成世界Boss(管理员); routes to boss_handlers.handle_spawn_boss."""
        if not self._is_boss_enabled():
            yield event.plain_result("🛠️ 世界Boss玩法正在维护中，敬请期待！")
            return
        if not self._check_boss_admin(event):
            yield event.plain_result("❌ 你没有权限生成Boss！此指令仅限管理员使用。")
            return

        success, msg, boss = await self.boss_handlers.handle_spawn_boss()
        yield event.plain_result(msg)

        if success and boss:
            await self._broadcast_boss_spawn(boss)

    # ===== 排行榜指令 =====

    @filter.command(CMD_RANK_LEVEL, "查看境界排行榜")
    @require_whitelist
    async def handle_rank_level(self, event: AstrMessageEvent):
        """Command 「境界排行」- 查看境界排行榜; routes to ranking_handlers.handle_rank_level."""
        async for r in self.ranking_handlers.handle_rank_level(event):
            yield r

    @filter.command(CMD_RANK_POWER, "查看战力排行榜")
    @require_whitelist
    async def handle_rank_power(self, event: AstrMessageEvent):
        """Command 「战力排行」- 查看战力排行榜; routes to ranking_handlers.handle_rank_power."""
        async for r in self.ranking_handlers.handle_rank_power(event):
            yield r

    @filter.command(CMD_RANK_WEALTH, "查看财富排行榜")
    @require_whitelist
    async def handle_rank_wealth(self, event: AstrMessageEvent):
        """Command 「灵石排行」- 查看财富排行榜; routes to ranking_handlers.handle_rank_wealth."""
        async for r in self.ranking_handlers.handle_rank_wealth(event):
            yield r

    @filter.command(CMD_RANK_DEPOSIT, "查看存款排行榜")
    @require_whitelist
    async def handle_rank_deposit(self, event: AstrMessageEvent):
        """Command 「存款排行」- 查看存款排行榜; routes to ranking_handlers.handle_rank_deposit."""
        async for r in self.ranking_handlers.handle_rank_deposit(event):
            yield r

    # ===== 战斗指令 =====

    @filter.command(CMD_DUEL, "与其他玩家决斗(消耗气血)")
    @require_whitelist
    async def handle_duel(self, event: AstrMessageEvent, target: str = ""):
        """Command 「决斗」- 与其他玩家决斗(消耗气血); routes to combat_handlers.handle_duel."""
        async for r in self.combat_handlers.handle_duel(event, target):
            yield r

    @filter.command(CMD_SPAR, "与其他玩家切磋(无消耗)")
    @require_whitelist
    async def handle_spar(self, event: AstrMessageEvent, target: str = ""):
        """Command 「切磋」- 与其他玩家切磋(无消耗); routes to combat_handlers.handle_spar."""
        async for r in self.combat_handlers.handle_spar(event, target):
            yield r

    # ===== 秘境指令 =====
    @filter.command(CMD_RIFT_LIST, "查看秘境列表")
    @require_whitelist
    async def handle_rift_list(self, event: AstrMessageEvent):
        """Command 「秘境列表」- 查看秘境列表; routes to rift_handlers.handle_rift_list."""
        async for r in self.rift_handlers.handle_rift_list(event):
            yield r

    @filter.command(CMD_RIFT_EXPLORE, "探索秘境")
    @require_whitelist
    async def handle_rift_explore(self, event: AstrMessageEvent, rift_id: int = 0):
        """Command 「探索秘境」- 探索秘境; routes to rift_handlers.handle_rift_explore."""
        if not self._is_pve_enabled():
            yield event.plain_result("🛠️ 秘境玩法正在维护中，敬请期待！")
            return
        async for r in self.rift_handlers.handle_rift_explore(event, rift_id):
            yield r

    @filter.command(CMD_RIFT_COMPLETE, "完成秘境探索")
    @require_whitelist
    async def handle_rift_complete(self, event: AstrMessageEvent):
        """Command 「完成探索」- 完成秘境探索; routes to rift_mgr.finish_exploration (with bounty progress updates)."""
        user_id = event.get_sender_id()
        success, msg, reward_data = await self.rift_mgr.finish_exploration(user_id)

        # 如果秘境探索成功完成，更新悬赏进度
        if success and reward_data:
            player = await self.db.get_player_by_id(user_id)
            if player:
                has_progress, bounty_msg = await self.bounty_mgr.add_bounty_progress(
                    player, "rift", 1
                )
                if has_progress:
                    msg += bounty_msg
            # 师承任务链：PvE 胜利计数（失败不影响秘境主流程）
            if reward_data.get("pve_won"):
                try:
                    master_msg = await self.sect_mgr.advance_master_progress(
                        user_id, "win_pve"
                    )
                    if master_msg:
                        msg += master_msg
                except Exception:
                    logger.warning(
                        "【修仙插件】师承任务PvE胜场推进失败（秘境）", exc_info=True
                    )

        yield event.plain_result(msg)

    @filter.command(CMD_RIFT_EXIT, "退出秘境")
    @require_whitelist
    async def handle_rift_exit(self, event: AstrMessageEvent):
        """Command 「退出秘境」- 退出秘境; routes to rift_handlers.handle_rift_exit."""
        async for r in self.rift_handlers.handle_rift_exit(event):
            yield r

    # ===== 历练指令 =====
    @filter.command(CMD_ADVENTURE_START, "开始历练")
    @require_whitelist
    async def handle_adventure_start(self, event: AstrMessageEvent, route: str = ""):
        """Command 「开始历练」- 开始历练; routes to adventure_handlers.handle_start_adventure."""
        async for r in self.adventure_handlers.handle_start_adventure(event, route):
            yield r

    @filter.command(CMD_ADVENTURE_COMPLETE, "完成历练")
    @require_whitelist
    async def handle_adventure_complete(self, event: AstrMessageEvent):
        """Command 「完成历练」- 完成历练; routes to adventure_mgr.finish_adventure (with bounty progress updates)."""
        user_id = event.get_sender_id()
        success, msg, reward_data = await self.adventure_mgr.finish_adventure(user_id)

        # 如果历练成功完成，更新悬赏进度
        if success and reward_data:
            player = await self.db.get_player_by_id(user_id)
            if player:
                bounty_tag = reward_data.get("bounty_tag", "adventure")
                bounty_value = reward_data.get("bounty_progress", 1)
                has_progress, bounty_msg = await self.bounty_mgr.add_bounty_progress(
                    player, bounty_tag, bounty_value
                )
                if has_progress:
                    msg += bounty_msg
            # 师承任务链：历练完成 + PvE 胜利计数（各自独立 try/except，
            # 任一失败不影响另一条的反馈消息，也不影响历练主流程）
            master_msg = None
            try:
                master_msg = await self.sect_mgr.advance_master_progress(
                    user_id, "adventure_complete"
                )
            except Exception:
                logger.warning(
                    "【修仙插件】师承任务进度推进失败（历练完成）", exc_info=True
                )
            if reward_data.get("pve_won"):
                try:
                    win_msg = await self.sect_mgr.advance_master_progress(
                        user_id, "win_pve"
                    )
                    if win_msg:
                        master_msg = (master_msg or "") + win_msg
                except Exception:
                    logger.warning(
                        "【修仙插件】师承任务进度推进失败（历练PvE胜利）",
                        exc_info=True,
                    )
            if master_msg:
                msg += master_msg

        yield event.plain_result(msg)

    @filter.command(CMD_ADVENTURE_STATUS, "查看历练状态")
    @require_whitelist
    async def handle_adventure_status(self, event: AstrMessageEvent):
        """Command 「历练状态」- 查看历练状态; routes to adventure_handlers.handle_adventure_status."""
        async for r in self.adventure_handlers.handle_adventure_status(event):
            yield r

    @filter.command(CMD_ADVENTURE_INFO, "查看历练系统说明")
    @require_whitelist
    async def handle_adventure_info(self, event: AstrMessageEvent):
        """Command 「历练信息」- 查看历练系统说明; routes to adventure_handlers.handle_adventure_info."""
        async for r in self.adventure_handlers.handle_adventure_info(event):
            yield r

    # ===== 炼丹指令 =====
    @filter.command(CMD_ALCHEMY_RECIPES, "查看丹药配方")
    @require_whitelist
    async def handle_alchemy_recipes(self, event: AstrMessageEvent):
        """Command 「丹药配方」- 查看丹药配方; routes to alchemy_handlers.handle_recipes."""
        async for r in self.alchemy_handlers.handle_recipes(event):
            yield r

    @filter.command(CMD_ALCHEMY_CRAFT, "炼制丹药")
    @require_whitelist
    async def handle_alchemy_craft(self, event: AstrMessageEvent, pill_id: int = 0):
        """Command 「炼丹」- 炼制丹药; routes to alchemy_handlers.handle_craft."""
        async for r in self.alchemy_handlers.handle_craft(event, pill_id):
            yield r

    # ===== 传承指令 =====
    @filter.command(CMD_IMPART_INFO, "查看传承信息")
    @require_whitelist
    async def handle_impart_info(self, event: AstrMessageEvent):
        """Command 「传承信息」- 查看传承信息; routes to impart_handlers.handle_impart_info."""
        async for r in self.impart_handlers.handle_impart_info(event):
            yield r

    # ===== Phase 1: 道号系统 =====
    @filter.command(CMD_CHANGE_NICKNAME, "修改道号")
    @require_whitelist
    async def handle_change_nickname(self, event: AstrMessageEvent, new_name: str = ""):
        """Command 「改道号」- 修改道号; routes to nickname_handler.handle_change_nickname."""
        async for r in self.nickname_handler.handle_change_nickname(event, new_name):
            yield r

    # ===== Phase 2: 灵石银行 =====
    @filter.command(CMD_BANK_INFO, "查看银行信息")
    @require_whitelist
    async def handle_bank_info(self, event: AstrMessageEvent):
        """Command 「银行」- 查看银行信息; routes to bank_handlers.handle_bank_info."""
        async for r in self.bank_handlers.handle_bank_info(event):
            yield r

    @filter.command(CMD_BANK_DEPOSIT, "存入灵石")
    @require_whitelist
    async def handle_bank_deposit(self, event: AstrMessageEvent, amount: int = 0):
        """Command 「存灵石」- 存入灵石; routes to bank_handlers.handle_deposit."""
        async for r in self.bank_handlers.handle_deposit(event, amount):
            yield r

    @filter.command(CMD_BANK_WITHDRAW, "取出灵石")
    @require_whitelist
    async def handle_bank_withdraw(self, event: AstrMessageEvent, amount: int = 0):
        """Command 「取灵石」- 取出灵石; routes to bank_handlers.handle_withdraw."""
        async for r in self.bank_handlers.handle_withdraw(event, amount):
            yield r

    @filter.command(CMD_BANK_INTEREST, "领取利息")
    @require_whitelist
    async def handle_bank_interest(self, event: AstrMessageEvent):
        """Command 「领取利息」- 领取利息; routes to bank_handlers.handle_claim_interest."""
        async for r in self.bank_handlers.handle_claim_interest(event):
            yield r

    @filter.command(CMD_BANK_LOAN, "申请贷款")
    @require_whitelist
    async def handle_bank_loan(self, event: AstrMessageEvent, amount: int = 0):
        """Command 「贷款」- 申请贷款; routes to bank_handlers.handle_loan."""
        async for r in self.bank_handlers.handle_loan(event, amount):
            yield r

    @filter.command(CMD_BANK_REPAY, "偿还贷款")
    @require_whitelist
    async def handle_bank_repay(self, event: AstrMessageEvent):
        """Command 「还款」- 偿还贷款; routes to bank_handlers.handle_repay."""
        async for r in self.bank_handlers.handle_repay(event):
            yield r

    @filter.command(CMD_BANK_TRANSACTIONS, "查看银行流水")
    @require_whitelist
    async def handle_bank_transactions(self, event: AstrMessageEvent):
        """Command 「银行流水」- 查看银行流水; routes to bank_handlers.handle_transactions."""
        async for r in self.bank_handlers.handle_transactions(event):
            yield r

    @filter.command(CMD_BANK_BREAKTHROUGH_LOAN, "申请突破贷款")
    @require_whitelist
    async def handle_bank_breakthrough_loan(
        self, event: AstrMessageEvent, amount: int = 0
    ):
        """Command 「突破贷款」- 申请突破贷款; routes to bank_handlers.handle_breakthrough_loan."""
        async for r in self.bank_handlers.handle_breakthrough_loan(event, amount):
            yield r

    # ===== Phase 2: 悬赏令 =====
    @filter.command(CMD_BOUNTY_LIST, "查看悬赏任务")
    @require_whitelist
    async def handle_bounty_list(self, event: AstrMessageEvent):
        """Command 「悬赏令」- 查看悬赏任务; routes to bounty_handlers.handle_bounty_list."""
        async for r in self.bounty_handlers.handle_bounty_list(event):
            yield r

    @filter.command(CMD_BOUNTY_ACCEPT, "接取悬赏任务")
    @require_whitelist
    async def handle_bounty_accept(self, event: AstrMessageEvent, bounty_id: int = 0):
        """Command 「接取悬赏」- 接取悬赏任务; routes to bounty_handlers.handle_accept_bounty."""
        async for r in self.bounty_handlers.handle_accept_bounty(event, bounty_id):
            yield r

    @filter.command(CMD_BOUNTY_STATUS, "查看悬赏状态")
    @require_whitelist
    async def handle_bounty_status(self, event: AstrMessageEvent):
        """Command 「悬赏状态」- 查看悬赏状态; routes to bounty_handlers.handle_bounty_status."""
        async for r in self.bounty_handlers.handle_bounty_status(event):
            yield r

    @filter.command(CMD_BOUNTY_COMPLETE, "完成悬赏任务")
    @require_whitelist
    async def handle_bounty_complete(self, event: AstrMessageEvent):
        """Command 「完成悬赏」- 完成悬赏任务; routes to bounty_handlers.handle_complete_bounty."""
        async for r in self.bounty_handlers.handle_complete_bounty(event):
            yield r

    @filter.command(CMD_BOUNTY_ABANDON, "放弃悬赏任务")
    @require_whitelist
    async def handle_bounty_abandon(self, event: AstrMessageEvent):
        """Command 「放弃悬赏」- 放弃悬赏任务; routes to bounty_handlers.handle_abandon_bounty."""
        async for r in self.bounty_handlers.handle_abandon_bounty(event):
            yield r

    # ===== Phase 3: 传承PK =====
    @filter.command(CMD_IMPART_CHALLENGE, "发起传承挑战")
    @require_whitelist
    async def handle_impart_challenge(self, event: AstrMessageEvent, target: str = ""):
        """Command 「传承挑战」- 发起传承挑战; routes to impart_pk_handlers.handle_impart_challenge."""
        async for r in self.impart_pk_handlers.handle_impart_challenge(event, target):
            yield r

    @filter.command(CMD_IMPART_RANKING, "查看传承排行")
    @require_whitelist
    async def handle_impart_ranking(self, event: AstrMessageEvent):
        """Command 「传承排行」- 查看传承排行; routes to impart_pk_handlers.handle_impart_ranking."""
        async for r in self.impart_pk_handlers.handle_impart_ranking(event):
            yield r

    # ===== Phase 4: 洞天福地 =====
    @filter.command(CMD_BLESSED_LAND_INFO, "查看洞天信息")
    @require_whitelist
    async def handle_blessed_land_info(self, event: AstrMessageEvent):
        """Command 「我的洞天」- 查看洞天信息; routes to blessed_land_handlers.handle_blessed_land_info."""
        async for r in self.blessed_land_handlers.handle_blessed_land_info(event):
            yield r

    @filter.command(CMD_BLESSED_LAND_BUY, "购买洞天")
    @require_whitelist
    async def handle_blessed_land_buy(
        self, event: AstrMessageEvent, land_type: int = 0
    ):
        """Command 「购买洞天」- 购买洞天; routes to blessed_land_handlers.handle_purchase."""
        async for r in self.blessed_land_handlers.handle_purchase(event, land_type):
            yield r

    @filter.command(CMD_BLESSED_LAND_UPGRADE, "升级洞天")
    @require_whitelist
    async def handle_blessed_land_upgrade(self, event: AstrMessageEvent):
        """Command 「升级洞天」- 升级洞天; routes to blessed_land_handlers.handle_upgrade."""
        async for r in self.blessed_land_handlers.handle_upgrade(event):
            yield r

    @filter.command(CMD_BLESSED_LAND_COLLECT, "收取洞天产出")
    @require_whitelist
    async def handle_blessed_land_collect(self, event: AstrMessageEvent):
        """Command 「洞天收取」- 收取洞天产出; routes to blessed_land_handlers.handle_collect."""
        async for r in self.blessed_land_handlers.handle_collect(event):
            yield r

    # ===== Phase 4: 灵田 =====
    @filter.command(CMD_SPIRIT_FARM_INFO, "查看灵田")
    @require_whitelist
    async def handle_spirit_farm_info(self, event: AstrMessageEvent):
        """Command 「我的灵田」- 查看灵田; routes to spirit_farm_handlers.handle_farm_info."""
        async for r in self.spirit_farm_handlers.handle_farm_info(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_CREATE, "开垦灵田")
    @require_whitelist
    async def handle_spirit_farm_create(self, event: AstrMessageEvent):
        """Command 「开垦灵田」- 开垦灵田; routes to spirit_farm_handlers.handle_create_farm."""
        async for r in self.spirit_farm_handlers.handle_create_farm(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_PLANT, "种植灵草")
    @require_whitelist
    async def handle_spirit_farm_plant(
        self, event: AstrMessageEvent, herb_name: str = ""
    ):
        """Command 「种植」- 种植灵草; routes to spirit_farm_handlers.handle_plant."""
        async for r in self.spirit_farm_handlers.handle_plant(event, herb_name):
            yield r

    @filter.command(CMD_SPIRIT_FARM_HARVEST, "收获灵草")
    @require_whitelist
    async def handle_spirit_farm_harvest(self, event: AstrMessageEvent):
        """Command 「收获」- 收获灵草; routes to spirit_farm_handlers.handle_harvest."""
        async for r in self.spirit_farm_handlers.handle_harvest(event):
            yield r

    @filter.command(CMD_SPIRIT_FARM_UPGRADE, "升级灵田")
    @require_whitelist
    async def handle_spirit_farm_upgrade(self, event: AstrMessageEvent):
        """Command 「升级灵田」- 升级灵田; routes to spirit_farm_handlers.handle_upgrade_farm."""
        async for r in self.spirit_farm_handlers.handle_upgrade_farm(event):
            yield r

    # ===== Phase 4: 双修 =====
    @filter.command(CMD_DUAL_CULT_REQUEST, "发起双修")
    @require_whitelist
    async def handle_dual_cult_request(self, event: AstrMessageEvent, target: str = ""):
        """Command 「双修」- 发起双修; routes to dual_cult_handlers.handle_dual_request."""
        async for r in self.dual_cult_handlers.handle_dual_request(event, target):
            yield r

    @filter.command(CMD_DUAL_CULT_ACCEPT, "接受双修")
    @require_whitelist
    async def handle_dual_cult_accept(self, event: AstrMessageEvent):
        """Command 「接受双修」- 接受双修; routes to dual_cult_handlers.handle_accept."""
        async for r in self.dual_cult_handlers.handle_accept(event):
            yield r

    @filter.command(CMD_DUAL_CULT_REJECT, "拒绝双修")
    @require_whitelist
    async def handle_dual_cult_reject(self, event: AstrMessageEvent):
        """Command 「拒绝双修」- 拒绝双修; routes to dual_cult_handlers.handle_reject."""
        async for r in self.dual_cult_handlers.handle_reject(event):
            yield r

    # ===== Phase 4: 天地灵眼 =====
    @filter.command(CMD_SPIRIT_EYE_INFO, "查看灵眼")
    @require_whitelist
    async def handle_spirit_eye_info(self, event: AstrMessageEvent):
        """Command 「灵眼信息」- 查看灵眼; routes to spirit_eye_handlers.handle_spirit_eye_info."""
        async for r in self.spirit_eye_handlers.handle_spirit_eye_info(event):
            yield r

    @filter.command(CMD_SPIRIT_EYE_CLAIM, "抢占灵眼")
    @require_whitelist
    async def handle_spirit_eye_claim(self, event: AstrMessageEvent, eye_id: int = 0):
        """Command 「抢占灵眼」- 抢占灵眼; routes to spirit_eye_handlers.handle_claim."""
        async for r in self.spirit_eye_handlers.handle_claim(event, eye_id):
            yield r

    @filter.command(CMD_SPIRIT_EYE_COLLECT, "收取灵眼产出")
    @require_whitelist
    async def handle_spirit_eye_collect(self, event: AstrMessageEvent):
        """Command 「灵眼收取」- 收取灵眼产出; routes to spirit_eye_handlers.handle_collect."""
        async for r in self.spirit_eye_handlers.handle_collect(event):
            yield r

    @filter.command(CMD_SPIRIT_EYE_RELEASE, "释放灵眼")
    @require_whitelist
    async def handle_spirit_eye_release(self, event: AstrMessageEvent):
        """Command 「释放灵眼」- 释放灵眼; routes to spirit_eye_handlers.handle_release."""
        async for r in self.spirit_eye_handlers.handle_release(event):
            yield r

    # ===== GM 系统指令 =====
    @filter.command(CMD_GM, "GM 管理命令")
    @require_whitelist
    async def handle_gm(self, event: AstrMessageEvent, args: GreedyStr):
        """Command 「修仙GM」- GM 管理命令; routes to gm_handler.handle_gm."""
        if not self._check_gm_admin(event):
            yield event.plain_result("❌ 你没有权限使用修仙GM命令！")
            return
        async for r in self.gm_handler.handle_gm(event, args):
            yield r

    @filter.command(CMD_GM_HELP, "GM 帮助命令")
    @require_whitelist
    async def handle_gm_help(self, event: AstrMessageEvent):
        """Command 「修仙GM帮助」- GM 帮助命令; routes to gm_handler.handle_gm_help."""
        if not self._check_gm_admin(event):
            yield event.plain_result("❌ 你没有权限使用修仙GM帮助命令！")
            return
        async for r in self.gm_handler.handle_gm_help(event):
            yield r
