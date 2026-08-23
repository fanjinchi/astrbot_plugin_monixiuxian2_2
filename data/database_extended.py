# data/database_extended.py
"""
扩展数据库操作类，包含宗门、Boss、秘境等新系统的CRUD方法
"""

import json

import aiosqlite

from ..models_extended import Boss, BuffInfo, LegacyInstance, Rift, Sect, UserCd


class DatabaseExtended:
    """数据库扩展操作类"""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # ===== 宗门系统 CRUD =====

    async def create_sect(self, sect: Sect):
        """创建宗门"""
        await self.conn.execute(
            """
            INSERT INTO sects (
                sect_name, sect_owner, sect_scale, sect_used_stone,
                sect_fairyland, sect_materials, mainbuff, secbuff, elixir_room_level,
                is_system, faction_id, status, destruction_tier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sect.sect_name,
                sect.sect_owner,
                sect.sect_scale,
                sect.sect_used_stone,
                sect.sect_fairyland,
                sect.sect_materials,
                sect.mainbuff,
                sect.secbuff,
                sect.elixir_room_level,
                sect.is_system,
                sect.faction_id,
                sect.status,
                sect.destruction_tier,
            ),
        )
        await self.conn.commit()

        # 获取刚插入的sect_id
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_sect_by_id(self, sect_id: int) -> Sect | None:
        """根据ID获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_id = ?", (sect_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None

    async def get_sect_by_owner(self, owner_id: str) -> Sect | None:
        """根据宗主ID获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_owner = ?", (owner_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None

    async def get_sect_by_name(self, sect_name: str) -> Sect | None:
        """根据宗门名称获取宗门信息"""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE sect_name = ?", (sect_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None

    async def get_sect_by_faction_id(self, faction_id: str) -> Sect | None:
        """Get a system sect by its sect_factions.json faction ID."""
        async with self.conn.execute(
            "SELECT * FROM sects WHERE faction_id = ?", (faction_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Sect(**dict(row))
            return None

    async def update_sect(self, sect: Sect, commit: bool = True):
        """更新宗门信息

        Args:
            sect: 宗门对象
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute(
            """
            UPDATE sects SET
                sect_name = ?, sect_owner = ?, sect_scale = ?, sect_used_stone = ?,
                sect_fairyland = ?, sect_materials = ?, mainbuff = ?, secbuff = ?,
                elixir_room_level = ?, is_system = ?, faction_id = ?, status = ?,
                destruction_tier = ?
            WHERE sect_id = ?
            """,
            (
                sect.sect_name,
                sect.sect_owner,
                sect.sect_scale,
                sect.sect_used_stone,
                sect.sect_fairyland,
                sect.sect_materials,
                sect.mainbuff,
                sect.secbuff,
                sect.elixir_room_level,
                sect.is_system,
                sect.faction_id,
                sect.status,
                sect.destruction_tier,
                sect.sect_id,
            ),
        )
        if commit:
            await self.conn.commit()

    async def delete_sect(self, sect_id: int):
        """删除宗门"""
        await self.conn.execute("DELETE FROM sects WHERE sect_id = ?", (sect_id,))
        await self.conn.commit()

    async def get_all_sects(self) -> list[Sect]:
        """获取所有宗门"""
        async with self.conn.execute(
            "SELECT * FROM sects ORDER BY sect_scale DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [Sect(**dict(row)) for row in rows]

    async def update_sect_materials(
        self, sect_id: int, materials: int, operation: int = 1, commit: bool = True
    ):
        """更新宗门资材

        Args:
            sect_id: 宗门ID
            materials: 资材数量
            operation: 1=增加, 2=减少
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        if operation == 1:
            await self.conn.execute(
                "UPDATE sects SET sect_materials = sect_materials + ? WHERE sect_id = ?",
                (materials, sect_id),
            )
        else:
            await self.conn.execute(
                "UPDATE sects SET sect_materials = sect_materials - ? WHERE sect_id = ?",
                (materials, sect_id),
            )
        if commit:
            await self.conn.commit()

    async def donate_to_sect(
        self, sect_id: int, stone_num: int, scale_ratio: int = 10, commit: bool = True
    ):
        """宗门捐献（增加灵石和建设度，建设度 = 灵石 × scale_ratio）

        Args:
            sect_id: 宗门ID
            stone_num: 捐献灵石数量
            scale_ratio: 建设度换算比率
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute(
            """
            UPDATE sects SET
                sect_used_stone = sect_used_stone + ?,
                sect_scale = sect_scale + ?
            WHERE sect_id = ?
            """,
            (stone_num, stone_num * scale_ratio, sect_id),
        )
        if commit:
            await self.conn.commit()

    # ===== BuffInfo 系统 CRUD =====

    async def create_buff_info(self, user_id: str):
        """初始化用户的buff信息

        Note: v22 migration rebuilt buff_info as (id, user_id) only; the old
        buff columns are retired, so only the user_id row is created here.
        """
        await self.conn.execute(
            "INSERT OR IGNORE INTO buff_info (user_id) VALUES (?)",
            (user_id,),
        )
        await self.conn.commit()

    async def get_buff_info(self, user_id: str) -> BuffInfo | None:
        """获取用户buff信息"""
        async with self.conn.execute(
            "SELECT * FROM buff_info WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return BuffInfo(**dict(row))
            return None

    async def update_buff_info(self, buff_info: BuffInfo):
        """更新用户buff信息"""
        await self.conn.execute(
            """
            UPDATE buff_info SET
                main_buff = ?, sec_buff = ?, faqi_buff = ?, fabao_weapon = ?,
                armor_buff = ?, atk_buff = ?, blessed_spot = ?, sub_buff = ?
            WHERE user_id = ?
            """,
            (
                buff_info.main_buff,
                buff_info.sec_buff,
                buff_info.faqi_buff,
                buff_info.fabao_weapon,
                buff_info.armor_buff,
                buff_info.atk_buff,
                buff_info.blessed_spot,
                buff_info.sub_buff,
                buff_info.user_id,
            ),
        )
        await self.conn.commit()

    async def update_user_main_buff(self, user_id: str, buff_id: int):
        """更新用户主修功法"""
        await self.conn.execute(
            "UPDATE buff_info SET main_buff = ? WHERE user_id = ?", (buff_id, user_id)
        )
        await self.conn.commit()

    async def update_user_sec_buff(self, user_id: str, buff_id: int):
        """更新用户辅修功法"""
        await self.conn.execute(
            "UPDATE buff_info SET sec_buff = ? WHERE user_id = ?", (buff_id, user_id)
        )
        await self.conn.commit()

    # ===== Boss 系统 CRUD =====

    async def create_boss(self, boss: Boss) -> int:
        """创建Boss"""
        await self.conn.execute(
            """
            INSERT INTO boss (
                boss_name, boss_level, hp, max_hp, atk, defense,
                stone_reward, create_time, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                boss.boss_name,
                boss.boss_level,
                boss.hp,
                boss.max_hp,
                boss.atk,
                boss.defense,
                boss.stone_reward,
                boss.create_time,
                boss.status,
            ),
        )
        await self.conn.commit()

        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_active_boss(self) -> Boss | None:
        """获取当前存活的Boss"""
        async with self.conn.execute(
            "SELECT * FROM boss WHERE status = 1 ORDER BY create_time DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Boss(**dict(row))
            return None

    async def get_boss_by_id(self, boss_id: int) -> Boss | None:
        """根据ID获取Boss信息"""
        async with self.conn.execute(
            "SELECT * FROM boss WHERE boss_id = ?", (boss_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Boss(**dict(row))
            return None

    async def update_boss(self, boss: Boss):
        """更新Boss信息"""
        await self.conn.execute(
            """
            UPDATE boss SET
                boss_name = ?, boss_level = ?, hp = ?, max_hp = ?, atk = ?,
                defense = ?, stone_reward = ?, status = ?
            WHERE boss_id = ?
            """,
            (
                boss.boss_name,
                boss.boss_level,
                boss.hp,
                boss.max_hp,
                boss.atk,
                boss.defense,
                boss.stone_reward,
                boss.status,
                boss.boss_id,
            ),
        )
        await self.conn.commit()

    async def defeat_boss(self, boss_id: int):
        """标记Boss为已击败"""
        await self.conn.execute(
            "UPDATE boss SET status = 0 WHERE boss_id = ?", (boss_id,)
        )
        await self.conn.commit()

    # ===== 秘境系统 CRUD =====

    async def create_rift(self, rift: Rift) -> int:
        """创建秘境"""
        await self.conn.execute(
            """
            INSERT INTO rifts (
                rift_name, rift_level, required_level, rewards
            ) VALUES (?, ?, ?, ?)
            """,
            (rift.rift_name, rift.rift_level, rift.required_level, rift.rewards),
        )
        await self.conn.commit()

        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_rift_by_id(self, rift_id: int) -> Rift | None:
        """根据ID获取秘境信息"""
        async with self.conn.execute(
            "SELECT * FROM rifts WHERE rift_id = ?", (rift_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Rift(**dict(row))
            return None

    async def get_all_rifts(self) -> list[Rift]:
        """获取所有秘境"""
        async with self.conn.execute(
            "SELECT * FROM rifts ORDER BY rift_level ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [Rift(**dict(row)) for row in rows]

    # ===== 传承系统 CRUD（legacy_instances，v32 改版） =====

    async def create_legacy_instance(
        self,
        owner_id: str,
        legacy_type: str,
        sect_id: int | None = None,
        is_active: bool = False,
        commit: bool = True,
    ) -> int:
        """Create a legacy instance and return its row id.

        Args:
            owner_id: Owning player user ID.
            legacy_type: One of common/sect/adventure/rift.
            sect_id: Owning sect for sect-type legacies, else None.
            is_active: Whether the instance starts as the active one.
            commit: Whether to commit immediately (False inside outer txn).

        Returns:
            The new instance row id.
        """
        import time

        await self.conn.execute(
            """
            INSERT INTO legacy_instances
                (owner_id, legacy_type, impart_value, claimed_tiers, sect_id, is_active, acquired_at)
            VALUES (?, ?, 0, '[]', ?, ?, ?)
            """,
            (owner_id, legacy_type, sect_id, int(is_active), int(time.time())),
        )
        if commit:
            await self.conn.commit()
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_legacy_instance_by_id(
        self, instance_id: int
    ) -> LegacyInstance | None:
        """Get a legacy instance by primary key."""
        async with self.conn.execute(
            "SELECT * FROM legacy_instances WHERE id = ?", (instance_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._to_legacy(dict(row)) if row else None

    async def list_legacy_instances_by_owner(
        self, owner_id: str
    ) -> list[LegacyInstance]:
        """List all legacy instances of a player, newest first."""
        async with self.conn.execute(
            "SELECT * FROM legacy_instances WHERE owner_id = ? ORDER BY acquired_at DESC, id DESC",
            (owner_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._to_legacy(dict(row)) for row in rows]

    async def get_active_legacy_instance(self, owner_id: str) -> LegacyInstance | None:
        """Get the player's currently active (accumulating) legacy instance."""
        async with self.conn.execute(
            "SELECT * FROM legacy_instances WHERE owner_id = ? AND is_active = 1",
            (owner_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._to_legacy(dict(row)) if row else None

    @staticmethod
    def _to_legacy(row: dict) -> LegacyInstance:
        """Normalize a legacy_instances row dict into a LegacyInstance.

        SQLite is loosely typed: sect_id may come back as str/None while the
        model declares ``int | None``. Normalize at the DAO boundary.
        """
        if row.get("sect_id") is not None:
            row["sect_id"] = int(row["sect_id"])
        row["is_active"] = int(row.get("is_active", 0))
        return LegacyInstance(**row)

    async def set_active_legacy_instance(
        self, owner_id: str, instance_id: int, commit: bool = True
    ) -> bool:
        """Mark instance_id active for owner and deactivate the rest (atomic).

        Args:
            owner_id: 玩家 ID。
            instance_id: 要激活的传承实例 ID。
            commit: True 时自行 BEGIN IMMEDIATE 并提交（缺省）；False 时假定
                调用方已开启外层事务，不另起事务、不提交、失败也不回滚外层。

        Returns:
            False when the instance does not belong to the owner.
        """
        if commit:
            await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT id FROM legacy_instances WHERE id = ? AND owner_id = ?",
                (instance_id, owner_id),
            ) as cursor:
                if await cursor.fetchone() is None:
                    if commit:
                        await self.conn.rollback()
                    return False
            await self.conn.execute(
                "UPDATE legacy_instances SET is_active = 0 WHERE owner_id = ?",
                (owner_id,),
            )
            await self.conn.execute(
                "UPDATE legacy_instances SET is_active = 1 WHERE id = ?",
                (instance_id,),
            )
            if commit:
                await self.conn.commit()
            return True
        except Exception:
            if commit:
                await self.conn.rollback()
            raise

    async def clear_active_legacy_instance(
        self, owner_id: str, instance_id: int, commit: bool = True
    ):
        """Deactivate the given instance if it is the owner's active one.

        Used when an active instance is snatched/reclaimed/deleted.
        """
        await self.conn.execute(
            "UPDATE legacy_instances SET is_active = 0 WHERE id = ? AND owner_id = ?",
            (instance_id, owner_id),
        )
        if commit:
            await self.conn.commit()

    async def update_legacy_instance(
        self, instance: LegacyInstance, commit: bool = True
    ):
        """Update value/claimed/owner/active fields of a legacy instance.

        Args:
            instance: The instance to persist (matched by id).
            commit: Whether to commit immediately (False inside outer txn).
        """
        await self.conn.execute(
            """
            UPDATE legacy_instances SET
                owner_id = ?, legacy_type = ?, impart_value = ?, claimed_tiers = ?,
                sect_id = ?, is_active = ?
            WHERE id = ?
            """,
            (
                instance.owner_id,
                instance.legacy_type,
                instance.impart_value,
                instance.claimed_tiers,
                instance.sect_id,
                instance.is_active,
                instance.id,
            ),
        )
        if commit:
            await self.conn.commit()

    async def delete_legacy_instance(self, instance_id: int, commit: bool = True):
        """Delete a legacy instance by primary key."""
        await self.conn.execute(
            "DELETE FROM legacy_instances WHERE id = ?", (instance_id,)
        )
        if commit:
            await self.conn.commit()

    async def delete_legacy_instances_by_owner_sect(
        self, owner_id: str, sect_id: int, commit: bool = True
    ) -> int:
        """Delete the player's sect-bound legacy instances (leave-sect reclaim).

        Returns:
            Number of deleted rows.
        """
        cursor = await self.conn.execute(
            "DELETE FROM legacy_instances WHERE owner_id = ? AND legacy_type = 'sect' AND sect_id = ?",
            (owner_id, sect_id),
        )
        rowcount = cursor.rowcount
        await cursor.close()
        if commit:
            await self.conn.commit()
        return rowcount

    async def get_legacy_value_ranking(self, limit: int = 10) -> list[dict]:
        """Rank players by total impart value across all their instances."""
        rankings = []
        async with self.conn.execute(
            """
            SELECT owner_id, SUM(impart_value) AS total
            FROM legacy_instances
            GROUP BY owner_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            async for row in cursor:
                rankings.append({"user_id": row[0], "impart_value": row[1]})
        return rankings

    # ===== 传承 PK 冷却 / 被夺保护 =====

    async def get_impart_pk_cooldown(
        self, challenger_id: str, target_id: str
    ) -> int | None:
        """Get the last failure timestamp for a challenger→target pair, if any."""
        async with self.conn.execute(
            "SELECT failed_at FROM impart_pk_cooldown WHERE challenger_id = ? AND target_id = ?",
            (challenger_id, target_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def upsert_impart_pk_cooldown(
        self, challenger_id: str, target_id: str, failed_at: int, commit: bool = True
    ):
        """Record a challenge failure timestamp for a challenger→target pair."""
        await self.conn.execute(
            """
            INSERT INTO impart_pk_cooldown (challenger_id, target_id, failed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(challenger_id, target_id) DO UPDATE SET failed_at = excluded.failed_at
            """,
            (challenger_id, target_id, failed_at),
        )
        if commit:
            await self.conn.commit()

    async def get_impart_snatch_protection(self, user_id: str) -> int | None:
        """Get the player's last snatched timestamp, if any."""
        async with self.conn.execute(
            "SELECT snatched_at FROM impart_snatch_protection WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def upsert_impart_snatch_protection(
        self, user_id: str, snatched_at: int, commit: bool = True
    ):
        """Record/refresh the player's snatch protection timestamp."""
        await self.conn.execute(
            """
            INSERT INTO impart_snatch_protection (user_id, snatched_at)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET snatched_at = excluded.snatched_at
            """,
            (user_id, snatched_at),
        )
        if commit:
            await self.conn.commit()

    async def delete_impart_pk_cooldowns(
        self, challenger_id: str, commit: bool = True
    ) -> int:
        """Delete all challenge cooldowns where the player is the challenger.

        Returns:
            Number of deleted rows (cooldown entries for different targets).
        """
        async with self.conn.execute(
            "DELETE FROM impart_pk_cooldown WHERE challenger_id = ?", (challenger_id,)
        ) as cursor:
            deleted = cursor.rowcount
        if commit:
            await self.conn.commit()
        return deleted

    async def delete_impart_snatch_protection(
        self, user_id: str, commit: bool = True
    ) -> int:
        """Delete a player's snatch protection entry.

        Returns:
            1 if an entry was deleted, 0 otherwise.
        """
        async with self.conn.execute(
            "DELETE FROM impart_snatch_protection WHERE user_id = ?", (user_id,)
        ) as cursor:
            deleted = cursor.rowcount
        if commit:
            await self.conn.commit()
        return deleted

    # ===== 用户CD系统 CRUD =====

    async def create_user_cd(self, user_id: str, commit: bool = True):
        """初始化用户CD信息

        Args:
            user_id: 用户ID
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute(
            """
            INSERT INTO user_cd (user_id, type, create_time, scheduled_time)
            VALUES (?, 0, 0, 0)
            """,
            (user_id,),
        )
        if commit:
            await self.conn.commit()

    async def get_user_cd(self, user_id: str) -> UserCd | None:
        """获取用户CD信息"""
        async with self.conn.execute(
            "SELECT * FROM user_cd WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return UserCd(**dict(row))
            return None

    async def update_user_cd(self, user_cd: UserCd):
        """更新用户CD信息"""
        await self.conn.execute(
            """
            UPDATE user_cd SET
                type = ?, create_time = ?, scheduled_time = ?, extra_data = ?
            WHERE user_id = ?
            """,
            (
                user_cd.type,
                user_cd.create_time,
                user_cd.scheduled_time,
                user_cd.extra_data,
                user_cd.user_id,
            ),
        )
        await self.conn.commit()

    async def set_user_busy(
        self,
        user_id: str,
        busy_type: int,
        scheduled_time: int = 0,
        extra_data: dict = None,
        commit: bool = True,
    ):
        """设置用户忙碌状态（无 user_cd 行时自动插入，保证双层状态检查一致）

        Args:
            user_id: 用户ID
            busy_type: 0=空闲, 1=闭关, 2=历练, 3=探索秘境
            scheduled_time: 计划完成时间戳
            extra_data: 额外数据（如秘境ID等）
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        import time

        extra_json = json.dumps(extra_data or {}, ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT INTO user_cd (user_id, type, create_time, scheduled_time, extra_data)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                type = excluded.type,
                create_time = excluded.create_time,
                scheduled_time = excluded.scheduled_time,
                extra_data = excluded.extra_data
            """,
            (user_id, busy_type, int(time.time()), scheduled_time, extra_json),
        )
        if commit:
            await self.conn.commit()

    async def set_user_free(self, user_id: str):
        """设置用户为空闲状态"""
        await self.set_user_busy(user_id, 0, 0)

    # ===== 功法领悟系统 CRUD =====

    async def get_learned_skills(self, user_id: str) -> list[dict]:
        """Get the player's learned skills with star levels and source.

        Args:
            user_id: Player user ID.

        Returns:
            List of dicts with keys skill_id, star_level, source, learned_at,
            origin_sect_id, sect_bound.
        """
        skills = []
        async with self.conn.execute(
            "SELECT skill_id, star_level, source, learned_at, origin_sect_id, sect_bound "
            "FROM player_skills WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            async for row in cursor:
                skills.append(
                    {
                        "skill_id": row[0],
                        "star_level": row[1],
                        "source": row[2],
                        "learned_at": row[3],
                        "origin_sect_id": row[4],
                        "sect_bound": bool(row[5]),
                    }
                )
        return skills

    async def is_skill_learned(self, user_id: str, skill_id: str) -> bool:
        """Check whether the player has learned a skill."""
        async with self.conn.execute(
            "SELECT 1 FROM player_skills WHERE user_id = ? AND skill_id = ?",
            (user_id, skill_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def get_star_level(self, user_id: str, skill_id: str) -> int:
        """Get the star level of a learned skill (defaults to 1)."""
        async with self.conn.execute(
            "SELECT star_level FROM player_skills WHERE user_id = ? AND skill_id = ?",
            (user_id, skill_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 1

    async def learn_or_star_up(
        self,
        user_id: str,
        skill_id: str,
        source: str = "",
        max_star: int = 3,
        max_star_exp_compensation: int = 0,
        origin_sect_id: str | None = None,
        sect_bound: bool = False,
        commit: bool = True,
    ) -> tuple[bool, int]:
        """Learn a new skill or increment the star level if already learned.

        Args:
            user_id: Player user ID.
            skill_id: Skill ID to learn or star up.
            source: Comprehension source (e.g. breakthrough_success).
            max_star: Maximum star level (default 3).
            max_star_exp_compensation: Experience granted atomically (inside
                this transaction) when the skill is already at max_star.
            origin_sect_id: Sect ID the skill was learned from (only written
                on first learn; star-ups keep the original attribution).
            sect_bound: Whether the skill is inherently sect-bound (only
                passable to members of the same sect); stored on first learn.
            commit: When True (default), wrap the write in its own
                ``BEGIN IMMEDIATE`` transaction and commit it. Pass False
                when calling inside an outer transaction — no BEGIN is
                issued, nothing is committed or rolled back here, and the
                caller owns commit/rollback.

        Returns:
            (is_new_learn, new_star_level). If already at max_star,
            returns (False, max_star) without incrementing.
        """
        import time

        now = int(time.time())
        if commit:
            await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT star_level FROM player_skills WHERE user_id = ? AND skill_id = ?",
                (user_id, skill_id),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                await self.conn.execute(
                    """
                    INSERT INTO player_skills (
                        user_id, skill_id, star_level, source, learned_at,
                        origin_sect_id, sect_bound
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        skill_id,
                        1,
                        source,
                        now,
                        origin_sect_id,
                        int(sect_bound),
                    ),
                )
                if commit:
                    await self.conn.commit()
                return True, 1

            current_star = row[0]
            if current_star >= max_star:
                if max_star_exp_compensation > 0:
                    await self.conn.execute(
                        "UPDATE players SET experience = experience + ? WHERE user_id = ?",
                        (max_star_exp_compensation, user_id),
                    )
                if commit:
                    await self.conn.commit()
                return False, max_star

            new_star = current_star + 1
            await self.conn.execute(
                """
                UPDATE player_skills SET star_level = ?, source = ?, learned_at = ?
                WHERE user_id = ? AND skill_id = ?
                """,
                (new_star, source, now, user_id, skill_id),
            )
            if commit:
                await self.conn.commit()
            return False, new_star
        except Exception:
            if commit:
                await self.conn.rollback()
            raise

    # ===== Player扩展字段更新方法 =====

    async def update_player_hp_mp(self, user_id: str, hp: int, mp: int):
        """更新玩家HP（MP字段已废弃，保留参数仅作兼容）。"""
        await self.conn.execute(
            "UPDATE players SET hp = ? WHERE user_id = ?", (hp, user_id)
        )
        await self.conn.commit()

    async def update_player_sect_info(
        self, user_id: str, sect_id: int, sect_position: int, commit: bool = True
    ):
        """更新玩家宗门信息

        Args:
            user_id: 用户ID
            sect_id: 宗门ID
            sect_position: 宗门职位
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute(
            "UPDATE players SET sect_id = ?, sect_position = ? WHERE user_id = ?",
            (sect_id, sect_position, user_id),
        )
        if commit:
            await self.conn.commit()

    async def update_player_sect_contribution(self, user_id: str, contribution: int):
        """更新玩家宗门贡献度"""
        await self.conn.execute(
            "UPDATE players SET sect_contribution = ? WHERE user_id = ?",
            (contribution, user_id),
        )
        await self.conn.commit()

    async def increment_sect_task_count(
        self, user_id: str, count: int = 1, commit: bool = True
    ):
        """增加宗门任务完成次数

        Args:
            user_id: 用户ID
            count: 增加次数
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute(
            "UPDATE players SET sect_task = sect_task + ? WHERE user_id = ?",
            (count, user_id),
        )
        if commit:
            await self.conn.commit()

    async def reset_sect_tasks(self, commit: bool = True):
        """重置所有用户的宗门任务次数（定时任务）

        Args:
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute("UPDATE players SET sect_task = 0")
        if commit:
            await self.conn.commit()

    async def reset_sect_elixir_get(self, commit: bool = True):
        """重置所有用户的宗门丹药领取标记（定时任务）

        Args:
            commit: 是否立即提交；事务块内调用传 False，由外层统一 commit/rollback
        """
        await self.conn.execute("UPDATE players SET sect_elixir_get = 0")
        if commit:
            await self.conn.commit()

    async def get_sect_members(self, sect_id: int) -> list:
        """获取宗门所有成员"""
        from ..models import Player

        async with self.conn.execute(
            "SELECT * FROM players WHERE sect_id = ? ORDER BY sect_position ASC, level_index DESC",
            (sect_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            # 简化返回，只返回部分字段
            from dataclasses import fields

            PLAYER_FIELDS = {f.name for f in fields(Player)}
            return [
                Player(**{k: v for k, v in dict(row).items() if k in PLAYER_FIELDS})
                for row in rows
            ]

    # ===== Phase 2: 灵石银行 CRUD =====

    async def get_bank_account(self, user_id: str) -> dict | None:
        """获取银行账户信息"""
        async with self.conn.execute(
            "SELECT balance, last_interest_time FROM bank_accounts WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"balance": row[0], "last_interest_time": row[1]}
            return None

    async def update_bank_account(
        self, user_id: str, balance: int, last_interest_time: int
    ):
        """更新或创建银行账户"""
        await self.conn.execute(
            """
            INSERT INTO bank_accounts (user_id, balance, last_interest_time)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = excluded.balance,
                last_interest_time = excluded.last_interest_time
            """,
            (user_id, balance, last_interest_time),
        )
        await self.conn.commit()

    # ===== Phase 2: 悬赏令系统 CRUD =====

    async def get_active_bounty(self, user_id: str) -> dict | None:
        """获取用户当前进行中的悬赏任务"""
        async with self.conn.execute(
            "SELECT * FROM bounty_tasks WHERE user_id = ? AND status = 1", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def create_bounty(
        self,
        user_id: str,
        bounty_id: int,
        bounty_name: str,
        target_type: str,
        target_count: int,
        rewards: str,
        expire_time: int,
    ):
        """创建悬赏任务"""
        import time

        await self.conn.execute(
            """
            INSERT INTO bounty_tasks (
                user_id, bounty_id, bounty_name, target_type,
                target_count, current_progress, rewards,
                start_time, expire_time, status
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
            """,
            (
                user_id,
                bounty_id,
                bounty_name,
                target_type,
                target_count,
                rewards,
                int(time.time()),
                expire_time,
            ),
        )
        await self.conn.commit()

    async def update_bounty_progress(self, user_id: str, progress: int):
        """更新悬赏任务进度"""
        await self.conn.execute(
            "UPDATE bounty_tasks SET current_progress = ? WHERE user_id = ? AND status = 1",
            (progress, user_id),
        )
        await self.conn.commit()

    async def complete_bounty(self, user_id: str) -> bool:
        """完成悬赏任务"""
        await self.conn.execute(
            "UPDATE bounty_tasks SET status = 2 WHERE user_id = ? AND status = 1",
            (user_id,),
        )
        await self.conn.commit()
        return True

    async def cancel_bounty(self, user_id: str):
        """取消悬赏任务"""
        await self.conn.execute(
            "UPDATE bounty_tasks SET status = 0 WHERE user_id = ? AND status = 1",
            (user_id,),
        )
        await self.conn.commit()

    # ===== 系统配置 CRUD =====

    async def get_system_config(self, key: str) -> str | None:
        """获取系统配置"""
        async with self.conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_system_config(self, key: str, value: str):
        """设置系统配置"""
        import time

        await self.conn.execute(
            """
            INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, value, int(time.time()), value, int(time.time())),
        )
        await self.conn.commit()

    # ===== 赠予请求系统 CRUD =====

    async def create_pending_gift(
        self,
        receiver_id: str,
        sender_id: str,
        sender_name: str,
        item_name: str,
        count: int,
        expires_hours: int = 24,
    ) -> int:
        """创建赠予请求

        Args:
            receiver_id: 接收者ID
            sender_id: 发送者ID
            sender_name: 发送者名称
            item_name: 物品名称
            count: 物品数量
            expires_hours: 过期时间（小时），默认24小时

        Returns:
            新创建的赠予请求ID
        """
        import time

        now = int(time.time())
        expires_at = now + expires_hours * 3600

        await self.conn.execute(
            """
            INSERT INTO pending_gifts (
                receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (receiver_id, sender_id, sender_name, item_name, count, now, expires_at),
        )
        await self.conn.commit()

        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_pending_gift(self, receiver_id: str) -> dict | None:
        """获取接收者的待处理赠予请求（最新的一个）"""
        import time

        now = int(time.time())

        # 先清理过期的请求
        await self.cleanup_expired_gifts()

        async with self.conn.execute(
            """
            SELECT id, receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            FROM pending_gifts
            WHERE receiver_id = ? AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (receiver_id, now),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "receiver_id": row[1],
                    "sender_id": row[2],
                    "sender_name": row[3],
                    "item_name": row[4],
                    "count": row[5],
                    "created_at": row[6],
                    "expires_at": row[7],
                }
            return None

    async def get_all_pending_gifts(self, receiver_id: str) -> list[dict]:
        """获取接收者的所有待处理赠予请求"""
        import time

        now = int(time.time())

        async with self.conn.execute(
            """
            SELECT id, receiver_id, sender_id, sender_name, item_name, count, created_at, expires_at
            FROM pending_gifts
            WHERE receiver_id = ? AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (receiver_id, now),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "receiver_id": row[1],
                    "sender_id": row[2],
                    "sender_name": row[3],
                    "item_name": row[4],
                    "count": row[5],
                    "created_at": row[6],
                    "expires_at": row[7],
                }
                for row in rows
            ]

    async def delete_pending_gift(self, gift_id: int):
        """删除赠予请求"""
        await self.conn.execute("DELETE FROM pending_gifts WHERE id = ?", (gift_id,))
        await self.conn.commit()

    async def delete_pending_gift_by_receiver(self, receiver_id: str):
        """删除接收者的所有赠予请求"""
        await self.conn.execute(
            "DELETE FROM pending_gifts WHERE receiver_id = ?", (receiver_id,)
        )
        await self.conn.commit()

    async def cleanup_expired_gifts(self):
        """清理过期的赠予请求"""
        import time

        now = int(time.time())
        await self.conn.execute(
            "DELETE FROM pending_gifts WHERE expires_at < ?", (now,)
        )
        await self.conn.commit()

    # ===== Phase 3: 银行贷款系统 CRUD =====

    async def get_active_loan(self, user_id: str) -> dict | None:
        """获取用户当前活跃的贷款"""
        async with self.conn.execute(
            """SELECT id, user_id, principal, interest_rate, borrowed_at, due_at, status, loan_type
               FROM bank_loans WHERE user_id = ? AND status = 'active'""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "principal": row[2],
                    "interest_rate": row[3],
                    "borrowed_at": row[4],
                    "due_at": row[5],
                    "status": row[6],
                    "loan_type": row[7],
                }
            return None

    async def create_loan(
        self,
        user_id: str,
        principal: int,
        interest_rate: float,
        borrowed_at: int,
        due_at: int,
        loan_type: str = "normal",
    ) -> int:
        """创建贷款记录"""
        await self.conn.execute(
            """INSERT INTO bank_loans (user_id, principal, interest_rate, borrowed_at, due_at, status, loan_type)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (user_id, principal, interest_rate, borrowed_at, due_at, loan_type),
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def close_loan(self, loan_id: int):
        """关闭贷款（标记为已还清）"""
        await self.conn.execute(
            "UPDATE bank_loans SET status = 'closed' WHERE id = ?", (loan_id,)
        )
        await self.conn.commit()

    async def mark_loan_overdue(self, loan_id: int):
        """标记贷款逾期"""
        await self.conn.execute(
            "UPDATE bank_loans SET status = 'overdue' WHERE id = ?", (loan_id,)
        )
        await self.conn.commit()

    async def get_overdue_loans(self, current_time: int) -> list[dict]:
        """获取所有逾期贷款"""
        loans = []
        async with self.conn.execute(
            """SELECT id, user_id, principal, interest_rate, borrowed_at, due_at, loan_type
               FROM bank_loans WHERE status = 'active' AND due_at < ?""",
            (current_time,),
        ) as cursor:
            async for row in cursor:
                loans.append(
                    {
                        "id": row[0],
                        "user_id": row[1],
                        "principal": row[2],
                        "interest_rate": row[3],
                        "borrowed_at": row[4],
                        "due_at": row[5],
                        "loan_type": row[6],
                    }
                )
        return loans

    # ===== Phase 3: 银行交易流水 CRUD =====

    async def add_bank_transaction(
        self,
        user_id: str,
        trans_type: str,
        amount: int,
        balance_after: int,
        description: str,
        created_at: int,
    ):
        """添加银行交易流水"""
        await self.conn.execute(
            """INSERT INTO bank_transactions (user_id, trans_type, amount, balance_after, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, trans_type, amount, balance_after, description, created_at),
        )
        await self.conn.commit()

    async def get_bank_transactions(self, user_id: str, limit: int = 20) -> list[dict]:
        """获取用户银行交易流水"""
        transactions = []
        async with self.conn.execute(
            """SELECT id, trans_type, amount, balance_after, description, created_at
               FROM bank_transactions WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            async for row in cursor:
                transactions.append(
                    {
                        "id": row[0],
                        "trans_type": row[1],
                        "amount": row[2],
                        "balance_after": row[3],
                        "description": row[4],
                        "created_at": row[5],
                    }
                )
        return transactions

    async def get_deposit_ranking(self, limit: int = 10) -> list[dict]:
        """获取存款排行榜"""
        rankings = []
        async with self.conn.execute(
            """SELECT user_id, balance FROM bank_accounts
               WHERE balance > 0
               ORDER BY balance DESC LIMIT ?""",
            (limit,),
        ) as cursor:
            async for row in cursor:
                rankings.append({"user_id": row[0], "balance": row[1]})
        return rankings
