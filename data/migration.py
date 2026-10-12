# data/migration.py

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import aiosqlite

from astrbot.api import logger

if TYPE_CHECKING:
    from ..config_manager import ConfigManager

# v3.11.0 起不再向前兼容：历史逐版本迁移（v1→v32）已全部删除，
# 全新安装与旧库统一直接生成最新 schema。MIGRATION_TASKS 注册机制
# 保留，供后续版本（v33+）做真正的增量升级。
# v34: 删除测试秘境「试炼古境」（add-rift-encounters 脚手架验证完毕拆除）
# v35: players 健康分层（child A: base_hp 永久底子 / current_hp 战气血 /
# health_recovered_at 懒恢复锚点；max_hp 只算不落库）
#
# 版本归属链（child P: PVE 持久化与事务基座，design §1 冻结）：
# v36: 历练结算事实 + 效果消费幂等 + 持久疲劳（adventure_*）
# v37: 世界 Boss 实例/出生快照版本/挑战/每日次数/台账/贡献（world_boss_*）
# v38: 业务事件 outbox + 逐目标投递 claim（business_events / event_deliveries）
# 每版 migration task 与 _create_all_tables 共用同一建表函数（单一真源，
# 全新安装与逐版升级不可能漂移）；VERSION_SCHEMA_TABLES 声明每版拥有的表，
# 供 schema parity 测试构造「升级前」库存档。只有 SQLite 约束要求时才允许
# 继续拆连续 v39…，不得复用已发布版本做别的结构。
LATEST_DB_VERSION = 38

# 增量任务链的适用下限：v32 是 _create_all_tables 冻结的完整 schema 基线，
# 只有达到该版本的库才具备迁移任务依赖的全部表结构；更早的旧库必须走
# migrate() 的重建路径，否则增量任务会在缺失的表上崩溃
TASK_CHAIN_MIN_VERSION = 32

MIGRATION_TASKS: dict[
    int, Callable[[aiosqlite.Connection, ConfigManager], Awaitable[None]]
] = {}

# 每版拥有的表（child P 冻结的版本归属矩阵，design §1）。索引/触发器随表
# 一起归属对应版本；本表是 schema parity 测试构造「升级前」库存档的唯一依据
# ——测试按此 DROP 掉 v>=N 的表并把 db_info.version 回退到 N-1，再跑任务链，
# 结果必须与全新安装的归一化 schema 逐表一致。新增版本时必须同步登记，
# 否则 parity 测试无法复现该版本的升级前状态。
VERSION_SCHEMA_TABLES: dict[int, tuple[str, ...]] = {
    36: (
        "adventure_settlements",
        "adventure_effects",
        "adventure_fatigue",
    ),
    37: (
        "world_boss_instances",
        "world_boss_challenges",
        "world_boss_daily_attempts",
        "world_boss_ledger",
        "world_boss_contributions",
    ),
    38: (
        "business_events",
        "event_deliveries",
    ),
}


def migration(version: int):
    """注册数据库迁移任务的装饰器（后续版本 v33+ 使用）。"""

    def decorator(
        func: Callable[[aiosqlite.Connection, ConfigManager], Awaitable[None]],
    ):
        """Register func as the migration task for the given schema version."""
        MIGRATION_TASKS[version] = func
        return func

    return decorator


@migration(34)
async def _remove_trial_rift_v34(
    conn: aiosqlite.Connection, config_manager: ConfigManager
):
    """Delete test rift 「试炼古境」 (id 7) — teardown of the add-rift-encounters scaffold.

    v33（已随拆除移除）曾双播种该测试秘境；本任务对已升级的库存续删
    （幂等：行不存在时 DELETE 为 no-op）。全新安装/重建路径的
    _create_all_tables default_rifts 种子行已同步移除，不再产生该行。
    """
    await conn.execute("DELETE FROM rifts WHERE rift_id = 7")


@migration(35)
async def _players_health_layers_v35(
    conn: aiosqlite.Connection, config_manager: ConfigManager
):
    """v35（child A 健康地基）：players.hp 拆分为三层健康模型。

    - hp → base_hp（永久底子，RENAME COLUMN 保留数据）；
    - current_hp（战斗气血，不变式 0<=current<=动态 max）；
    - health_recovered_at（懒恢复锚点，unix 秒，0=未结算）。

    一次性回填服务（design D1）：每个现存玩家的 current_hp 初始化为
    迁移时刻的动态 max_hp（装备/心法聚合同 HealthService 计算路径，
    非裸 base_hp），锚点设为迁移时刻——升级当刻满血、无历史欠账。
    框架已在本任务外层 BEGIN 事务内执行（失败整体回滚、版本停在 v34），
    因此 ALTER+回填+版本推进原子生效。项目未上线，无双写/别名过渡。
    """
    import time

    cursor = await conn.execute("PRAGMA table_info(players)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "base_hp" in cols:
        # 幂等守卫：schema 已升级（重复执行不应二次改名/回填）。
        return
    if "hp" not in cols:
        raise RuntimeError("v35 迁移失败：players 表缺少 hp 列，schema 无法识别")

    await conn.execute("ALTER TABLE players RENAME COLUMN hp TO base_hp")
    await conn.execute(
        "ALTER TABLE players ADD COLUMN current_hp INTEGER NOT NULL DEFAULT 100"
    )
    await conn.execute(
        "ALTER TABLE players ADD COLUMN health_recovered_at INTEGER NOT NULL DEFAULT 0"
    )

    # 回填复用 HealthService.compute_max_hp（纯聚合，不触库），保证
    # 迁移口径与运行时恢复上限完全一致。
    from ..core.equipment_manager import EquipmentManager
    from ..core.health import HealthService
    from ..models import Player

    health = HealthService(
        db=None,
        config_manager=config_manager,
        equipment_manager=EquipmentManager(db=None),
    )
    migration_now = int(time.time())
    cursor = await conn.execute(
        "SELECT user_id, base_hp, level_index, cultivation_type, weapon, "
        "armor, main_technique, techniques FROM players"
    )
    rows = await cursor.fetchall()
    for (
        user_id,
        base_hp,
        level_index,
        cultivation_type,
        weapon,
        armor,
        main_technique,
        techniques,
    ) in rows:
        player = Player(
            user_id=user_id,
            base_hp=int(base_hp or 0),
            level_index=int(level_index or 0),
            cultivation_type=cultivation_type or "灵修",
            weapon=weapon or "",
            armor=armor or "",
            main_technique=main_technique or "",
            techniques=techniques or "[]",
        )
        max_hp = health.compute_max_hp(player)
        await conn.execute(
            "UPDATE players SET current_hp = ?, health_recovered_at = ? "
            "WHERE user_id = ?",
            (max_hp, migration_now, user_id),
        )

    # 结构校验（PRD：改名/加列后核验列存在），失败则框架回滚停在 v34。
    cursor = await conn.execute("PRAGMA table_info(players)")
    cols = {row[1] for row in await cursor.fetchall()}
    missing = {"base_hp", "current_hp", "health_recovered_at"} - cols
    if missing:
        raise RuntimeError(f"v35 迁移失败：players 缺少列 {sorted(missing)}")


async def _create_adventure_persistence_tables(conn: aiosqlite.Connection):
    """Create the v36 adventure persistence objects (settlement / effects / fatigue).

    单一真源：v36 migration task 与 _create_all_tables 都调用本函数，
    全新安装与逐版升级因此不可能漂移（PRD R1 的 fresh/upgrade 同构要求）。
    child P 只建「可被幂等消费的事实」，不实现逃跑判定、战斗结算或奖励发放。
    """
    # 历练结算事实：一次 adventure run 至多一条，字段是后续奖励服务的
    # 幂等消费输入（真实气血差、结局、档案版本），不含任何奖励声明。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS adventure_settlements (
            settlement_id TEXT PRIMARY KEY,
            adventure_run_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL
                REFERENCES players(user_id) ON DELETE CASCADE,
            encounter_id TEXT NOT NULL DEFAULT '',
            profile_id TEXT NOT NULL DEFAULT '',
            profile_version INTEGER NOT NULL DEFAULT 0,
            risk_level INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL DEFAULT '',
            hp_before INTEGER NOT NULL DEFAULT 0,
            hp_after INTEGER NOT NULL DEFAULT 0,
            fled INTEGER NOT NULL DEFAULT 0 CHECK (fled IN (0, 1)),
            defeated INTEGER NOT NULL DEFAULT 0 CHECK (defeated IN (0, 1)),
            settled_at INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_adventure_settlements_user "
        "ON adventure_settlements(user_id, settled_at DESC)"
    )

    # 效果消费 claim 表：消费者按 (consumer_name, settlement_id, effect_type)
    # 唯一，插入即领取、冲突即已消费（幂等重复投递不重复发放）。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS adventure_effects (
            effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            consumer_name TEXT NOT NULL,
            settlement_id TEXT NOT NULL
                REFERENCES adventure_settlements(settlement_id) ON DELETE CASCADE,
            effect_type TEXT NOT NULL,
            claimed_at INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE (consumer_name, settlement_id, effect_type)
        )
    """)

    # 持久疲劳（替代进程内 _route_cooldowns）：fatigue_until 是参与到期判定的
    # 绝对时间戳 → 必须登记 GM 时间快进（见 managers/adventure_manager.py）。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS adventure_fatigue (
            user_id TEXT PRIMARY KEY
                REFERENCES players(user_id) ON DELETE CASCADE,
            route_id TEXT NOT NULL DEFAULT '',
            fatigue_until INTEGER NOT NULL DEFAULT 0,
            last_settlement_id TEXT NOT NULL DEFAULT '',
            cas_version INTEGER NOT NULL DEFAULT 1
        )
    """)


@migration(36)
async def _adventure_persistence_v36(
    conn: aiosqlite.Connection, config_manager: ConfigManager
):
    """v36（child P）：历练结算事实、效果消费幂等表、持久疲劳表。

    纯建表，无历史数据搬迁：疲劳此前只存在于进程内字典（重启即丢），
    升级后从空表开始是正确语义（无人处于疲劳），不需要回填。
    框架已在本任务外层 BEGIN 事务内执行，失败整体回滚、版本停在 v35。
    """
    await _create_adventure_persistence_tables(conn)


async def _create_world_boss_persistence_tables(conn: aiosqlite.Connection):
    """Create the v37 world-boss persistence objects (instance / challenge / ledger).

    实例行同时承载不可变出生快照（birth_snapshot：技能、阶段规则等只在
    生成时复制一次的档案字段）与 CAS 版本号，使热更新 config 不会改变
    正在进行的战斗；终态转换由条件写入（state + cas_version 的 CAS）达成，
    repository 不实现阶段推进/末击判定（child D 的领域状态机）。
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_instances (
            instance_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            profile_version INTEGER NOT NULL DEFAULT 0,
            boss_name TEXT NOT NULL DEFAULT '',
            boss_level INTEGER NOT NULL DEFAULT 0,
            max_hp INTEGER NOT NULL DEFAULT 0,
            current_hp INTEGER NOT NULL DEFAULT 0,
            atk INTEGER NOT NULL DEFAULT 0,
            defense INTEGER NOT NULL DEFAULT 0,
            agility INTEGER NOT NULL DEFAULT 0,
            speed INTEGER NOT NULL DEFAULT 0,
            armor_value INTEGER NOT NULL DEFAULT 0,
            phase INTEGER NOT NULL DEFAULT 1 CHECK (phase BETWEEN 1 AND 3),
            state TEXT NOT NULL DEFAULT 'active'
                CHECK (state IN ('active', 'defeated', 'dissipated')),
            birth_snapshot TEXT NOT NULL DEFAULT '{}',
            spawned_at INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER NOT NULL DEFAULT 0,
            next_spawn_at INTEGER NOT NULL DEFAULT 0,
            terminated_at INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1,
            CHECK (current_hp >= 0),
            CHECK (current_hp <= max_hp)
        )
    """)
    # expires_at（48h 寿命）与 next_spawn_at（终态后的再生资格时刻）都是
    # 参与到期判定的绝对时间戳 → 登记 GM 时间快进（managers/boss_manager.py）。
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_world_boss_instances_state "
        "ON world_boss_instances(state, expires_at)"
    )

    # 挑战明细：challenge_id 即请求幂等键（同一 id 重放不二次扣次数/伤害）；
    # 伤害只等于本行记录的 hp_before - hp_after，不得用 max_hp - final_hp 重算。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_challenges (
            challenge_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL
                REFERENCES world_boss_instances(instance_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL
                REFERENCES players(user_id) ON DELETE CASCADE,
            date_key TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT '',
            damage_dealt INTEGER NOT NULL DEFAULT 0,
            hp_before INTEGER NOT NULL DEFAULT 0,
            hp_after INTEGER NOT NULL DEFAULT 0,
            player_hp_before INTEGER NOT NULL DEFAULT 0,
            player_hp_after INTEGER NOT NULL DEFAULT 0,
            fled INTEGER NOT NULL DEFAULT 0 CHECK (fled IN (0, 1)),
            is_last_hit INTEGER NOT NULL DEFAULT 0 CHECK (is_last_hit IN (0, 1)),
            phase_changed INTEGER NOT NULL DEFAULT 0,
            instance_cas_version INTEGER NOT NULL DEFAULT 0,
            attempted_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_world_boss_challenges_instance "
        "ON world_boss_challenges(instance_id, attempted_at)"
    )

    # 每日次数：date_key 是 Asia/Shanghai 自然日键，绝不能登记时间快进
    # （字段跳前不得顺手重置每日次数）；主键 (date_key, user_id) = 跨 Boss 全局
    # 每人每日一计（child D PRD R3：每名玩家每个自然日最多 3 次）。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_daily_attempts (
            date_key TEXT NOT NULL,
            user_id TEXT NOT NULL
                REFERENCES players(user_id) ON DELETE CASCADE,
            attempts_used INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (date_key, user_id)
        )
    """)

    # 贡献台账：每次成功挑战一条 append-only 事实，UNIQUE(instance_id,
    # challenge_id) 使台账写入本身幂等；是 Step 7 奖励输入的审计面。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_ledger (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL
                REFERENCES world_boss_instances(instance_id) ON DELETE CASCADE,
            challenge_id TEXT NOT NULL
                REFERENCES world_boss_challenges(challenge_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL
                REFERENCES players(user_id) ON DELETE CASCADE,
            profile_version INTEGER NOT NULL DEFAULT 0,
            damage_dealt INTEGER NOT NULL DEFAULT 0,
            recorded_at INTEGER NOT NULL DEFAULT 0,
            UNIQUE (instance_id, challenge_id)
        )
    """)

    # 按玩家累计贡献（instance × user）：条件累加，供结算与展示读取。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS world_boss_contributions (
            instance_id TEXT NOT NULL
                REFERENCES world_boss_instances(instance_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL
                REFERENCES players(user_id) ON DELETE CASCADE,
            profile_version INTEGER NOT NULL DEFAULT 0,
            total_damage INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            first_hit_at INTEGER NOT NULL DEFAULT 0,
            last_hit_at INTEGER NOT NULL DEFAULT 0,
            is_last_hit INTEGER NOT NULL DEFAULT 0 CHECK (is_last_hit IN (0, 1)),
            cas_version INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (instance_id, user_id)
        )
    """)


@migration(37)
async def _world_boss_persistence_v37(
    conn: aiosqlite.Connection, config_manager: ConfigManager
):
    """v37（child P）：世界 Boss 实例/出生快照/挑战/每日次数/台账/贡献表。

    新建独立实例表而不是改造旧 boss 表：旧表语义（status 1 存活/0 被击败、
    stone_reward 即时灵石）与新生命周期（active/defeated/dissipated + 真实
    伤害贡献）不同，Batch 4/5 切流前旧 CRUD 继续可用，两套并存。
    """
    await _create_world_boss_persistence_tables(conn)


async def _create_event_outbox_tables(conn: aiosqlite.Connection):
    """Create the v38 outbox objects (business events / per-destination delivery).

    事务内只写这两张表，网络投递在事务外消费（design §5：不把网络等待
    放进数据库事务）；claim 状态机 queued → dispatching → sent | queued |
    uncertain，uncertain 永不自动重试。本系统不提供 exactly-once 保证。
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS business_events (
            event_id TEXT PRIMARY KEY,
            business_key TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            occurred_at INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_events_type_time "
        "ON business_events(event_type, occurred_at)"
    )

    # 逐目标投递：UNIQUE(event_id, platform, group_id) 保证同一事件对同一
    # 群至多一条投递记录；某目标失败不重放已 sent 的其它目标。
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_deliveries (
            delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL
                REFERENCES business_events(event_id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            group_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued', 'dispatching', 'sent', 'uncertain')),
            claim_owner TEXT NOT NULL DEFAULT '',
            claim_expires_at INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            cas_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE (event_id, platform, group_id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_deliveries_claim "
        "ON event_deliveries(state, next_retry_at)"
    )


@migration(38)
async def _event_outbox_v38(conn: aiosqlite.Connection, config_manager: ConfigManager):
    """v38（child P）：业务事件表 + 逐目标投递（outbox）表。"""
    await _create_event_outbox_tables(conn)


async def _create_all_tables(conn: aiosqlite.Connection):
    """Create the current (v38) schema for a fresh database.

    唯一的建表入口：全新安装与旧库重建都走这里，保证两条路径 schema
    完全一致（不再存在多套历史建表函数漂移的问题）。v36 起新增的 PVE
    表由本函数直接调用各版本的共享建表函数，与 migration task 同源。
    """

    # 数据库版本信息表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS db_info (
            version INTEGER NOT NULL
        )
    """)

    # 玩家表 - 四主属性新框架
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL DEFAULT '',
            level_index INTEGER NOT NULL DEFAULT 0,
            spiritual_root TEXT NOT NULL DEFAULT '未知',
            cultivation_type TEXT NOT NULL DEFAULT '灵修',
            lifespan INTEGER NOT NULL DEFAULT 100,
            experience INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT '空闲',
            cultivation_start_time INTEGER NOT NULL DEFAULT 0,
            last_check_in_date TEXT NOT NULL DEFAULT '',
            level_up_rate INTEGER NOT NULL DEFAULT 0,
            breakthrough_fail_streak INTEGER NOT NULL DEFAULT 0,

            damage INTEGER NOT NULL DEFAULT 10,
            agility INTEGER NOT NULL DEFAULT 5,
            speed INTEGER NOT NULL DEFAULT 5,
            -- v35 健康分层：base_hp 永久底子、current_hp 战气血
            -- （0<=current<=运行时聚合的 max_hp，max 不落库）、
            -- health_recovered_at 懒恢复锚点（0=未结算，首次结算只认时钟）。
            base_hp INTEGER NOT NULL DEFAULT 100,
            current_hp INTEGER NOT NULL DEFAULT 100,
            health_recovered_at INTEGER NOT NULL DEFAULT 0,
            armor_value INTEGER NOT NULL DEFAULT 0,

            weapon TEXT NOT NULL DEFAULT '',
            armor TEXT NOT NULL DEFAULT '',
            main_technique TEXT NOT NULL DEFAULT '',
            techniques TEXT NOT NULL DEFAULT '[]',

            -- 功法领悟修习目标（已领悟技能存 player_skills 表）
            study_target TEXT NOT NULL DEFAULT '',
            battle_report_merge_count INTEGER NOT NULL DEFAULT 0,

            sect_id INTEGER NOT NULL DEFAULT 0,
            sect_position INTEGER NOT NULL DEFAULT 4,
            sect_contribution INTEGER NOT NULL DEFAULT 0,
            sect_task INTEGER NOT NULL DEFAULT 0,
            sect_elixir_get INTEGER NOT NULL DEFAULT 0,
            sect_treasure_claims TEXT NOT NULL DEFAULT '[]',
            sect_master_progress TEXT NOT NULL DEFAULT '{}',

            blessed_spot_flag INTEGER NOT NULL DEFAULT 0,
            blessed_spot_name TEXT NOT NULL DEFAULT '',

            active_pill_effects TEXT NOT NULL DEFAULT '[]',
            permanent_pill_gains TEXT NOT NULL DEFAULT '{}',
            has_resurrection_pill INTEGER NOT NULL DEFAULT 0,
            has_debuff_shield INTEGER NOT NULL DEFAULT 0,
            pills_inventory TEXT NOT NULL DEFAULT '{}',

            storage_ring TEXT NOT NULL DEFAULT '基础储物戒',
            storage_ring_items TEXT NOT NULL DEFAULT '{}',

            daily_pill_usage TEXT NOT NULL DEFAULT '{}',
            last_daily_reset TEXT NOT NULL DEFAULT ''
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_level ON players(level_index)"
    )

    # 商店表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shop (
            shop_id TEXT PRIMARY KEY,
            last_refresh_time INTEGER NOT NULL DEFAULT 0,
            current_items TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await conn.execute("""
        INSERT OR IGNORE INTO shop (shop_id, last_refresh_time, current_items)
        VALUES ('global', 0, '[]')
    """)

    # 宗门表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sects (
            sect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sect_name TEXT NOT NULL UNIQUE,
            sect_owner TEXT NOT NULL,
            sect_scale INTEGER NOT NULL DEFAULT 0,
            sect_used_stone INTEGER NOT NULL DEFAULT 0,
            sect_fairyland INTEGER NOT NULL DEFAULT 0,
            sect_materials INTEGER NOT NULL DEFAULT 0,
            mainbuff TEXT NOT NULL DEFAULT '0',
            secbuff TEXT NOT NULL DEFAULT '0',
            elixir_room_level INTEGER NOT NULL DEFAULT 0,
            is_system INTEGER NOT NULL DEFAULT 0,
            faction_id TEXT,
            status TEXT NOT NULL DEFAULT 'normal',
            destruction_tier TEXT
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sect_owner ON sects(sect_owner)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sect_scale ON sects(sect_scale DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sect_faction ON sects(faction_id)"
    )

    # Buff信息表（简化，旧字段废弃）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS buff_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_buff_user ON buff_info(user_id)")

    # Boss表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS boss (
            boss_id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_name TEXT NOT NULL,
            boss_level TEXT NOT NULL,
            hp INTEGER NOT NULL,
            max_hp INTEGER NOT NULL,
            atk INTEGER NOT NULL,
            defense INTEGER NOT NULL DEFAULT 0,
            stone_reward INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            status INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_boss_status ON boss(status, create_time DESC)"
    )

    # 秘境表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rifts (
            rift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rift_name TEXT NOT NULL,
            rift_level INTEGER NOT NULL,
            required_level INTEGER NOT NULL,
            rewards TEXT NOT NULL DEFAULT '{}'
        )
    """)

    # 传承实例表（一人多条，is_active 单激活；sect_id 与 sects.sect_id 同为 INTEGER）
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS legacy_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL,
            legacy_type TEXT NOT NULL DEFAULT 'common',
            impart_value INTEGER NOT NULL DEFAULT 0,
            claimed_tiers TEXT NOT NULL DEFAULT '[]',
            sect_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 0,
            acquired_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_legacy_owner ON legacy_instances(owner_id)"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_legacy_active_owner "
        "ON legacy_instances(owner_id) WHERE is_active = 1"
    )

    # 传承 PK 失败冷却表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS impart_pk_cooldown (
            challenger_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            failed_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (challenger_id, target_id)
        )
    """)

    # 传承被夺保护表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS impart_snatch_protection (
            user_id TEXT PRIMARY KEY,
            snatched_at INTEGER NOT NULL DEFAULT 0
        )
    """)

    # 用户CD表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_cd (
            user_id TEXT PRIMARY KEY,
            type INTEGER NOT NULL DEFAULT 0,
            create_time INTEGER NOT NULL DEFAULT 0,
            scheduled_time INTEGER NOT NULL DEFAULT 0,
            extra_data TEXT NOT NULL DEFAULT '{}'
        )
    """)

    # 赠予请求表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_name TEXT NOT NULL DEFAULT '',
            item_name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_gifts_receiver ON pending_gifts(receiver_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pending_gifts_expires ON pending_gifts(expires_at)"
    )

    # 银行账户表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            last_interest_time INTEGER NOT NULL DEFAULT 0
        )
    """)

    # 银行贷款表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            principal INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0.005,
            borrowed_at INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            loan_type TEXT NOT NULL DEFAULT 'normal',
            UNIQUE(user_id, status)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bank_loans_user ON bank_loans(user_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bank_loans_status ON bank_loans(status)"
    )

    # 银行交易流水表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            trans_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bank_trans_user ON bank_transactions(user_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bank_trans_time ON bank_transactions(created_at)"
    )

    # 悬赏任务表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bounty_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            bounty_id INTEGER NOT NULL,
            bounty_name TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_count INTEGER NOT NULL,
            current_progress INTEGER NOT NULL DEFAULT 0,
            rewards TEXT NOT NULL DEFAULT '{}',
            start_time INTEGER NOT NULL,
            expire_time INTEGER NOT NULL,
            status INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bounty_user ON bounty_tasks(user_id)"
    )

    # 洞天福地表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blessed_lands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            land_type INTEGER NOT NULL DEFAULT 1,
            land_name TEXT NOT NULL DEFAULT '小洞天',
            level INTEGER NOT NULL DEFAULT 1,
            exp_bonus REAL NOT NULL DEFAULT 0.05,
            gold_per_hour INTEGER NOT NULL DEFAULT 100,
            last_collect_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_blessed_lands_user ON blessed_lands(user_id)"
    )

    # 灵田表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            level INTEGER NOT NULL DEFAULT 1,
            crops TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spirit_farms_user ON spirit_farms(user_id)"
    )

    # 双修记录表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            last_dual_time INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dual_user ON dual_cultivation(user_id)"
    )

    # 天地灵眼表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS spirit_eyes (
            eye_id INTEGER PRIMARY KEY AUTOINCREMENT,
            eye_type INTEGER NOT NULL DEFAULT 1,
            eye_name TEXT NOT NULL DEFAULT '下品灵眼',
            exp_per_hour INTEGER NOT NULL DEFAULT 500,
            spawn_time INTEGER NOT NULL,
            owner_id TEXT,
            owner_name TEXT,
            claim_time INTEGER,
            last_collect_time INTEGER
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spirit_eyes_owner ON spirit_eyes(owner_id)"
    )

    # 双修请求表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dual_cultivation_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id TEXT NOT NULL,
            from_name TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dual_req_target ON dual_cultivation_requests(target_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dual_req_expires ON dual_cultivation_requests(expires_at)"
    )

    # 战斗冷却表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS combat_cooldowns (
            user_id TEXT PRIMARY KEY,
            last_duel_time INTEGER NOT NULL DEFAULT 0,
            last_spar_time INTEGER NOT NULL DEFAULT 0
        )
    """)

    # player_skills 表：独立存储玩家已领悟技能与星级
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS player_skills (
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            star_level INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT '',
            learned_at INTEGER NOT NULL DEFAULT 0,
            origin_sect_id TEXT,
            sect_bound INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, skill_id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_skills_user ON player_skills(user_id)"
    )

    # 系统配置表
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_system_config_updated
        ON system_config(updated_at)
    """)

    # === PVE 持久化基座（v36-v38，child P）===
    # 与对应 migration task 共用同一建表函数：全新安装的 schema 必须与
    # v34 → v35 → v36 → v37 → v38 逐版升级的结果逐表一致。
    await _create_adventure_persistence_tables(conn)
    await _create_world_boss_persistence_tables(conn)
    await _create_event_outbox_tables(conn)

    # 插入默认秘境数据
    import json

    default_rifts = [
        (1, "青云秘境", 1, 0, json.dumps({"exp": [500, 1500], "gold": [200, 800]})),
        (2, "落日峡谷", 2, 3, json.dumps({"exp": [1500, 4000], "gold": [500, 2000]})),
        (3, "万妖洞", 3, 6, json.dumps({"exp": [3000, 8000], "gold": [1000, 5000]})),
        (
            4,
            "玄冰地宫",
            4,
            10,
            json.dumps({"exp": [5000, 15000], "gold": [2000, 10000]}),
        ),
        (
            5,
            "上古遗迹",
            5,
            15,
            json.dumps({"exp": [10000, 30000], "gold": [5000, 20000]}),
        ),
        (
            6,
            "青云剑冢",
            3,
            3,
            json.dumps({"exp": [300, 900], "gold": [100, 400]}),
        ),
    ]
    for rift in default_rifts:
        await conn.execute(
            "INSERT OR IGNORE INTO rifts (rift_id, rift_name, rift_level, required_level, rewards) VALUES (?, ?, ?, ?, ?)",
            rift,
        )

    # 插入初始灵眼数据
    import time

    now = int(time.time())
    initial_eyes = [
        (1, "下品灵眼", 500, now),
        (1, "下品灵眼", 500, now),
        (2, "中品灵眼", 2000, now),
    ]
    for eye in initial_eyes:
        await conn.execute(
            "INSERT INTO spirit_eyes (eye_type, eye_name, exp_per_hour, spawn_time) VALUES (?, ?, ?, ?)",
            eye,
        )


async def _drop_all_tables(conn: aiosqlite.Connection):
    """Drop every user table (legacy databases being rebuilt).

    PRAGMA foreign_keys 切换由调用方在事务外完成（SQLite 禁止事务内修改）。
    """
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ) as cursor:
        tables = [row[0] for row in await cursor.fetchall()]
    for table in tables:
        await conn.execute(f'DROP TABLE IF EXISTS "{table}"')


class MigrationManager:
    """数据库迁移管理器"""

    def __init__(self, conn: aiosqlite.Connection, config_manager: ConfigManager):
        self.conn = conn
        self.config_manager = config_manager

    async def migrate_or_reset(self):
        """Bring the database up to LATEST_DB_VERSION; may reset all data.

        Four paths, one of which (path 3) wipes all data — a snapshot is
        taken to `<db>.v<old_version>.pre-reset.bak` before that happens:
        1. Fresh install (no db_info): `_create_all_tables()` builds the
           latest schema directly;
        2. v32+ schema with pending registered incremental tasks: upgrade
           per-version, one transaction per version;
        3. Old database (version < LATEST without usable migration tasks,
           including libs below TASK_CHAIN_MIN_VERSION): since v3.11.0 there
           is no forward compatibility — warn, back up, then rebuild to the
           latest schema (**all data is reset**);
        4. current_version > LATEST (downgrade attempt): raise RuntimeError
           and refuse to run, since the new schema may break on old code.
        """
        await self.conn.execute("PRAGMA foreign_keys = ON")
        async with self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='db_info'"
        ) as cursor:
            if await cursor.fetchone() is None:
                logger.info("未检测到数据库版本，将进行全新安装...")
                await self.conn.execute("BEGIN")
                try:
                    await _create_all_tables(self.conn)
                    await self.conn.execute(
                        "INSERT INTO db_info (version) VALUES (?)", (LATEST_DB_VERSION,)
                    )
                    await self.conn.commit()
                except Exception:
                    await self.conn.rollback()
                    raise
                logger.info(f"数据库已初始化到最新版本: v{LATEST_DB_VERSION}")
                return

        async with self.conn.execute("SELECT version FROM db_info") as cursor:
            row = await cursor.fetchone()
            current_version = row[0] if row else 0

        logger.info(
            f"当前数据库版本: v{current_version}, 最新版本: v{LATEST_DB_VERSION}"
        )

        # 后续版本注册的增量迁移（v33+）优先走任务链，但仅限已具备 v32 完整
        # schema 的库：更早的旧库缺少任务依赖的表结构（如 rifts），进任务链
        # 只会在缺失的表上崩溃，必须落入下方重建路径
        pending = []
        if current_version >= TASK_CHAIN_MIN_VERSION:
            pending = [
                v
                for v in sorted(MIGRATION_TASKS.keys())
                if current_version < v <= LATEST_DB_VERSION
            ]
        if pending:
            logger.info("检测到数据库需要升级...")
            for version in pending:
                logger.info(f"正在执行数据库升级: v{current_version} -> v{version} ...")
                await self.conn.execute("BEGIN")
                try:
                    await MIGRATION_TASKS[version](self.conn, self.config_manager)
                    await self.conn.execute(
                        "UPDATE db_info SET version = ?", (version,)
                    )
                    await self.conn.commit()
                    current_version = version
                    logger.info(f"数据库升级成功: v{version}")
                except Exception as e:
                    await self.conn.rollback()
                    logger.error(f"数据库升级失败: v{version}. 错误: {str(e)}")
                    raise
            logger.info(f"数据库已升级到最新版本: v{LATEST_DB_VERSION}")
            return

        if current_version < LATEST_DB_VERSION:
            # 不再向前兼容：历史迁移已删除，重建为最新 schema（数据重置）
            logger.warning(
                f"数据库版本 v{current_version} 低于 v{LATEST_DB_VERSION}，"
                "且该项目不再向前兼容；将重建数据库到最新 schema（旧数据将被清空）。"
            )
            # PRAGMA foreign_keys 必须在事务外切换（SQLite 禁止事务内修改），
            # 否则 drop 顺序任意时外键约束可能阻断删除
            await self.conn.execute("PRAGMA foreign_keys = OFF")
            # 备份必须在 BEGIN 之前：VACUUM 不能在事务内执行；失败不阻断重置
            await self._backup_before_reset(current_version)
            await self.conn.execute("BEGIN")
            try:
                await _drop_all_tables(self.conn)
                await _create_all_tables(self.conn)
                # db_info 已被 DROP 重建为空表，需 INSERT 而非 UPDATE
                await self.conn.execute(
                    "INSERT INTO db_info (version) VALUES (?)", (LATEST_DB_VERSION,)
                )
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise
            finally:
                await self.conn.execute("PRAGMA foreign_keys = ON")
            logger.info(f"数据库已重建到最新版本: v{LATEST_DB_VERSION}")
        elif current_version > LATEST_DB_VERSION:
            # 版本倒退（插件回滚/新库旧插件）：schema 可能比本插件新，继续运行
            # 会产生 no such table/column 等偶发错误，必须显式失败
            raise RuntimeError(
                f"数据库版本 v{current_version} 高于本插件支持的 v{LATEST_DB_VERSION}，"
                "不允许降级运行，请使用与数据库匹配的插件版本。"
            )
        else:
            logger.info("数据库已是最新版本，无需升级。")

    async def _backup_before_reset(self, current_version: int) -> None:
        """Snapshot the live database before a destructive rebuild.

        Runs only on the reset path, after `PRAGMA foreign_keys = OFF` and
        before `BEGIN` (VACUUM cannot run inside a transaction). Uses
        `VACUUM INTO` on the open connection so the backup is a consistent
        snapshot even with WAL/unflushed pages. Failure degrades to an ERROR
        log — the reset proceeds without a backup, same as the historical
        behavior, so an old database is never left unable to start.

        Args:
            current_version: Database version read before the reset; used in
                the backup file name `<db>.v<current_version>.pre-reset.bak`.
        """
        try:
            # The manager only holds a connection, not a path: resolve the
            # main database file via database_list (row[2] = filename) instead
            # of adding a constructor parameter.
            async with self.conn.execute("PRAGMA database_list") as cursor:
                rows = await cursor.fetchall()
            db_path = next((row[2] for row in rows if row[1] == "main"), "")
            if not db_path:
                # :memory: connections report an empty filename; VACUUM INTO
                # would succeed and write a stray .bak into the pytest CWD.
                logger.warning("db 路径为空（:memory: 连接），跳过重置前备份")
                return
            backup_path = f"{db_path}.v{current_version}.pre-reset.bak"
            # Escape single quotes in the path for the SQL string literal.
            await self.conn.execute(
                f"VACUUM INTO '{backup_path.replace(chr(39), chr(39) * 2)}'"
            )
            logger.info(f"重置前已备份数据库至: {backup_path}")
        except Exception as e:
            # 备份失败不阻断重置（现状本就无备份，不劣化），但必须明示
            logger.error(f"备份失败，未备份即重置: {e}")
