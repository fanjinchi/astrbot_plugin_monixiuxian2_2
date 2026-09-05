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
LATEST_DB_VERSION = 34

# 增量任务链的适用下限：v32 是 _create_all_tables 冻结的完整 schema 基线，
# 只有达到该版本的库才具备迁移任务依赖的全部表结构；更早的旧库必须走
# migrate() 的重建路径，否则增量任务会在缺失的表上崩溃
TASK_CHAIN_MIN_VERSION = 32

MIGRATION_TASKS: dict[
    int, Callable[[aiosqlite.Connection, ConfigManager], Awaitable[None]]
] = {}


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


async def _create_all_tables(conn: aiosqlite.Connection):
    """Create the current (v32) schema for a fresh database.

    唯一的建表入口：全新安装与旧库重建都走这里，保证两条路径 schema
    完全一致（不再存在多套历史建表函数漂移的问题）。
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
            hp INTEGER NOT NULL DEFAULT 100,
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

    async def migrate(self):
        """Bring the database up to LATEST_DB_VERSION.

        三种路径：
        1. 全新安装（无 db_info）：直接 `_create_all_tables()` 生成最新 schema；
        2. 当前库已具备 v32 完整 schema（>= TASK_CHAIN_MIN_VERSION）且存在
           已注册的后续迁移任务（版本高于当前）：按版本升序逐任务升级，
           每个版本一个事务；
        3. 旧版数据库（version < LATEST 且没有可用的迁移任务，含低于
           TASK_CHAIN_MIN_VERSION 的库）：v3.11.0 起不再向前兼容——警告后
           重建为最新 schema（数据重置）。
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
