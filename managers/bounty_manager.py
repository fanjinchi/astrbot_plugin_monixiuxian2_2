# managers/bounty_manager.py
"""悬赏令系统管理器"""

import json
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from astrbot.api import logger

from ..data import DataBase
from ..models import Player

if TYPE_CHECKING:
    from ..core import StorageRingManager

__all__ = ["BountyManager"]


class BountyManager:
    """悬赏令管理器"""

    BOUNTY_CACHE_DURATION = 600  # 任务列表缓存10分钟
    CONFIG_FILE = (
        Path(__file__).resolve().parents[1] / "config" / "bounty_templates.json"
    )
    ADVENTURE_CONFIG_FILE = (
        Path(__file__).resolve().parents[1] / "config" / "adventure_config.json"
    )
    DEFAULT_CONFIG = {
        "difficulties": {
            "easy": {
                "name": "F级",
                "stone_scale": 1.0,
                "exp_scale": 1.0,
                "min_level": 0,
            }
        },
        "templates": [
            {
                "id": 1,
                "name": "击退妖兽",
                "difficulty": "easy",
                "category": "巡山",
                "progress_tags": ["adventure_scout"],
                "min_target": 3,
                "max_target": 5,
                "time_limit": 3600,
                "reward": {"stone": 300, "exp": 2500},
                "item_table": "hunt",
                "description": "驱逐骚扰山门的妖兽。",
            }
        ],
        "item_tables": {
            "hunt": [
                {"name": "灵兽毛皮", "weight": 40, "min": 1, "max": 3},
                {"name": "妖兽精血", "weight": 30, "min": 1, "max": 2},
                {"name": "玄铁", "weight": 30, "min": 1, "max": 2},
            ]
        },
    }

    def __init__(
        self, db: DataBase, storage_ring_manager: Optional["StorageRingManager"] = None
    ):
        self.db = db
        self.storage_ring_manager = storage_ring_manager
        self._bounty_cache: dict[str, dict] = {}
        self.difficulties: dict[str, dict] = {}
        self.templates_by_id: dict[int, dict] = {}
        self.templates_by_diff: dict[str, list[dict]] = {}
        self.item_tables: dict[str, list[dict]] = {}
        self.adventure_tag_meta: dict[str, dict[str, int]] = {}
        self.reload_config()

    # -------- 配置 --------

    def reload_config(self):
        """Reload bounty templates, difficulty scaling, and item tables from config/bounty_templates.json."""
        config = self._load_config_file()
        self.difficulties = config.get(
            "difficulties", self.DEFAULT_CONFIG["difficulties"]
        )
        self.item_tables = config.get("item_tables", self.DEFAULT_CONFIG["item_tables"])
        self.templates_by_id = {}
        self.templates_by_diff = {}
        for tpl in config.get("templates", []):
            tpl_copy = dict(tpl)
            tpl_copy["progress_tags"] = [
                str(tag).lower() for tag in tpl_copy.get("progress_tags", [])
            ]
            self.templates_by_id[tpl_copy["id"]] = tpl_copy
            self.templates_by_diff.setdefault(tpl_copy["difficulty"], []).append(
                tpl_copy
            )
        logger.info(f"悬赏配置加载完成：{len(self.templates_by_id)} 条模板")
        self._load_adventure_meta()

    def _load_config_file(self) -> dict:
        """Read the bounty config JSON, falling back to DEFAULT_CONFIG when missing or invalid."""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error(f"加载 bounty_templates.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_CONFIG

    def _load_adventure_meta(self):
        """Load adventure route durations/fatigue used to calibrate bounty time limits."""
        self.adventure_tag_meta = {}
        if not self.ADVENTURE_CONFIG_FILE.exists():
            return
        try:
            with open(self.ADVENTURE_CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for route in data.get("routes", []):
                tag = str(route.get("bounty_tag", "")).lower()
                if not tag:
                    continue
                self.adventure_tag_meta[tag] = {
                    "duration": int(route.get("duration", 3600)),
                    "fatigue": int(route.get("fatigue_cooldown", 0)),
                }
            logger.info("已加载冒险路线元数据用于悬赏校准")
        except Exception as exc:
            logger.warning(f"加载冒险路线配置失败，将使用默认时限: {exc}")

    # -------- 列表 & 缓存 --------

    def _get_cached_bounties(
        self, user_id: str, scope: str = "global"
    ) -> list[dict] | None:
        """Return the user's cached bounty list for the scope while still within BOUNTY_CACHE_DURATION."""
        cache = self._bounty_cache.get(f"{user_id}:{scope}")
        if cache and cache["expire_time"] > int(time.time()):
            return cache["bounties"]
        return None

    def _set_cached_bounties(
        self, user_id: str, bounties: list[dict], scope: str = "global"
    ):
        """Cache a user's generated bounty list for the scope with an expiry timestamp."""
        self._bounty_cache[f"{user_id}:{scope}"] = {
            "bounties": bounties,
            "expire_time": int(time.time()) + self.BOUNTY_CACHE_DURATION,
        }

    async def get_bounty_list(
        self, player: Player, scope: str = "global"
    ) -> list[dict]:
        """获取悬赏列表。scope="global" 仅公共悬赏（无 sect_id）；scope="sect" 仅玩家所属宗门的专属悬赏。"""
        cached = self._get_cached_bounties(player.user_id, scope)
        if cached:
            return cached

        faction_id = await self._get_player_faction_id(player)
        plan = self._get_difficulty_plan(player.level_index)
        bounties: list[dict] = []
        for diff in plan:
            entry = self._build_bounty_entry(diff, player, faction_id, scope)
            if entry:
                bounties.append(entry)

        self._set_cached_bounties(player.user_id, bounties, scope)
        return bounties

    async def _get_player_faction_id(self, player: Player) -> str | None:
        """Resolve the faction_id of the player's sect (None when sectless or a player-built sect)."""
        sect_id = getattr(player, "sect_id", 0)
        if not isinstance(sect_id, int) or not sect_id:
            return None
        if self.db is None or self.db.ext is None:
            return None
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect is None:
            return None
        return getattr(sect, "faction_id", None)

    def _get_difficulty_plan(self, level_index: int) -> list[str]:
        """Pick available difficulty tiers for the player level (easy+normal; +hard at >=7; +elite at >=12)."""
        plan = ["easy", "normal"]
        if level_index >= 7:
            plan.append("hard")
        if level_index >= 12:
            plan.append("elite")
        return [diff for diff in plan if diff in self.difficulties]

    def _pick_template(
        self, difficulty: str, faction_id: str | None = None, scope: str = "global"
    ) -> dict | None:
        """Weighted-random pick of a bounty template within a difficulty tier.

        scope="global": only public templates (no ``sect_id``); scope="sect":
        only templates whose ``sect_id`` matches the player's sect faction.
        """
        if scope == "sect":
            templates = [
                tpl
                for tpl in self.templates_by_diff.get(difficulty, [])
                if tpl.get("sect_id") and tpl.get("sect_id") == faction_id
            ]
        else:
            templates = [
                tpl
                for tpl in self.templates_by_diff.get(difficulty, [])
                if not tpl.get("sect_id")
            ]
        if not templates:
            return None
        total = sum(max(1, tpl.get("weight", 1)) for tpl in templates)
        roll = random.randint(1, total)
        upto = 0
        for tpl in templates:
            upto += max(1, tpl.get("weight", 1))
            if roll <= upto:
                return tpl
        return templates[0]

    def _build_bounty_entry(
        self,
        difficulty: str,
        player: Player,
        faction_id: str | None = None,
        scope: str = "global",
    ) -> dict | None:
        """Build one bounty list entry: rolled target count, scaled reward, calibrated time limit, progress tags."""
        template = self._pick_template(difficulty, faction_id, scope)
        if not template:
            return None
        diff_cfg = self.difficulties.get(difficulty, {})
        target = random.randint(
            template.get("min_target", 1), template.get("max_target", 1)
        )
        reward = self._calculate_reward(template, diff_cfg, player, target)
        progress_tags = [str(tag).lower() for tag in template.get("progress_tags", [])]
        time_limit = self._calculate_time_limit(template, target)
        return {
            "id": template["id"],
            "name": template["name"],
            "category": template.get("category", "任务"),
            "difficulty": difficulty,
            "difficulty_name": diff_cfg.get("name", difficulty),
            "description": template.get("description", ""),
            "count": target,
            "reward": reward,
            "time_limit": time_limit,
            "progress_tags": progress_tags,
            "item_table": template.get("item_table", "gather"),
            "sect_id": template.get("sect_id"),
        }

    def _calculate_reward(
        self, template: dict, diff_cfg: dict, player: Player, target: int
    ) -> dict[str, int]:
        """Scale template stone/exp rewards by difficulty scale, rolled-progress factor, and level bonus."""
        base_reward = template.get("reward", {"stone": 200, "exp": 2000})
        stone = base_reward.get("stone", 0)
        exp = base_reward.get("exp", 0)
        level_bonus = 1 + max(0, player.level_index - 3) * 0.06
        progress_factor = max(1, target) / max(1, template.get("min_target", 1))
        stone_scale = diff_cfg.get("stone_scale", 1.0)
        exp_scale = diff_cfg.get("exp_scale", 1.0)
        final_stone = int(stone * stone_scale * progress_factor * level_bonus)
        final_exp = int(exp * exp_scale * progress_factor * level_bonus)
        return {"stone": final_stone, "exp": final_exp}

    def _calculate_time_limit(self, template: dict, target: int) -> int:
        """Derive the time limit from adventure route unit time x target plus a fatigue/queue buffer."""
        base_limit = template.get("time_limit", 3600)
        unit = self._get_adventure_unit_time(template)
        if not unit:
            return base_limit
        # 预估完成所有进度所需的最小时间
        expected = unit * target
        # 追加容错缓冲，兼顾疲劳与队列
        buffer = max(600, unit // 2)
        return max(base_limit, expected + buffer)

    def _get_adventure_unit_time(self, template: dict) -> int | None:
        """Estimate per-progress duration from adventure route metadata (duration + fatigue); None if unknown."""
        durations = []
        for tag in template.get("progress_tags", []):
            meta = self.adventure_tag_meta.get(tag.lower())
            if meta:
                # 考虑路线基础时长+部分休整
                durations.append(meta.get("duration", 0) + meta.get("fatigue", 0))
        if not durations:
            return None
        return max(60, min(durations))

    def _active_bounty_is_sect(self, active: dict) -> bool | None:
        """Classify the active bounty by its template's ``sect_id``; None when the template is gone from config."""
        template = self.templates_by_id.get(active["bounty_id"])
        if template is None:
            return None
        return bool(template.get("sect_id"))

    def _scope_mismatch_message(
        self, is_sect: bool | None, scope: str, global_action: str, sect_action: str
    ) -> str | None:
        """Return a cross-scope rejection for status/complete/abandon, guiding to the other entry; None when the operation may proceed."""
        if is_sect is None:
            # 模板已从配置移除时不阻断，避免玩家悬赏卡死
            return None
        if scope == "sect" and not is_sect:
            # 宗门入口直接渲染消息（自带 ❌），全局入口由 handler 统一加 ❌ 前缀，勿重复
            return f"❌ 你当前进行中的悬赏为公共悬赏，请使用 /{global_action} 操作。"
        if scope == "global" and is_sect:
            return (
                f"你当前进行中的悬赏为宗门悬赏，请使用 /宗门 悬赏 {sect_action} 操作。"
            )
        return None

    # -------- 接取与状态 --------

    async def accept_bounty(
        self, player: Player, bounty_id: int, scope: str = "global"
    ) -> tuple[bool, str]:
        """Accept a bounty from the player's cached list (transactional; one active bounty at a time, enforces the post-abandon cooldown).

        scope="global" 只接受公共悬赏，scope="sect" 只接受本宗专属悬赏；
        类型/归属校验先于缓存与冷却检查，保证两个入口的分流提示确定可见。
        """
        if bounty_id <= 0:
            return False, "无效的悬赏编号。"

        template = self.templates_by_id.get(bounty_id)
        if not template:
            return False, "该悬赏已失效，请刷新列表。"

        # 入口分流校验（先于缓存/冷却检查，确保提示确定）
        template_sect = template.get("sect_id")
        if scope == "sect":
            if not template_sect:
                return False, "❌ 该悬赏为公共委托，请发送 /接取悬赏 接取。"
            faction_id = await self._get_player_faction_id(player)
            if faction_id != template_sect:
                return False, "❌ 该悬赏为其他宗门的专属委托，仅面向其门下弟子发布。"
        elif template_sect:
            # 全局 handler 失败时统一加 ❌ 前缀，此处不内联，避免出现 "❌ ❌"
            return False, "该悬赏为宗门专属委托，请发送 /宗门 悬赏 查看与接取。"

        diff_key = template.get("difficulty", "easy")
        self.difficulties.get(diff_key, {})
        cached_bounties = self._get_cached_bounties(player.user_id, scope)
        cached = None
        if cached_bounties:
            cached = next((b for b in cached_bounties if b["id"] == bounty_id), None)
        if not cached:
            if scope == "sect":
                return False, "⚠️ 请先发送 /宗门 悬赏 查看列表后再接取。"
            return False, "⚠️ 悬赏列表已刷新，请先发送 /悬赏令 重新查看后再接取。"

        now = int(time.time())
        time_limit = cached.get("time_limit", template.get("time_limit", 3600))

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if active:
                await self.db.conn.rollback()
                return (
                    False,
                    f"你已有进行中的悬赏：{active['bounty_name']}，请先完成或放弃。",
                )

            cd_key = f"bounty_abandon_cd_{player.user_id}"
            cd_value = await self.db.ext.get_system_config(cd_key)
            if cd_value:
                cd_time = int(cd_value)
                if now < cd_time:
                    await self.db.conn.rollback()
                    remaining = (cd_time - now) // 60 or 1
                    return (
                        False,
                        f"你刚放弃过悬赏，还需等待 {remaining} 分钟才能再次接取。",
                    )

            expire_time = now + time_limit
            rewards_json = json.dumps(
                {
                    "stone": cached["reward"]["stone"],
                    "exp": cached["reward"]["exp"],
                    "difficulty": diff_key,
                    "difficulty_name": cached.get("difficulty_name", diff_key),
                    "item_table": cached.get("item_table"),
                    "description": cached.get("description", ""),
                    "progress_tags": cached.get("progress_tags", []),
                },
                ensure_ascii=False,
            )

            await self.db.conn.execute(
                """
                INSERT INTO bounty_tasks (
                    user_id, bounty_id, bounty_name, target_type,
                    target_count, current_progress, rewards,
                    start_time, expire_time, status
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
                """,
                (
                    player.user_id,
                    bounty_id,
                    template["name"],
                    cached.get("category", template.get("category", "任务")),
                    cached["count"],
                    rewards_json,
                    now,
                    expire_time,
                ),
            )
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        return True, (
            f"🎯 接取悬赏成功！\n"
            f"任务：{template['name']}（{cached.get('difficulty_name', diff_key)}）\n"
            f"目标：完成 {cached['count']} 次\n"
            f"奖励：{cached['reward']['stone']:,} 灵石 + {cached['reward']['exp']:,} 修为\n"
            f"时限：{time_limit // 60} 分钟"
        )

    async def check_bounty_status(
        self, player: Player, scope: str = "global"
    ) -> tuple[bool, str]:
        """Format the player's active bounty progress and remaining time for display (scope 分流：跨类型引导到对方入口)。"""
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            hint = "/宗门 悬赏" if scope == "sect" else "/悬赏令"
            return (
                False,
                f"你当前没有进行中的悬赏任务。\n使用 {hint} 查看可接取的任务。",
            )

        mismatch = self._scope_mismatch_message(
            self._active_bounty_is_sect(active),
            scope,
            "悬赏状态",
            "进度",
        )
        if mismatch:
            return False, mismatch

        rewards = json.loads(active["rewards"])
        remaining = max(0, active["expire_time"] - int(time.time()))
        progress = active.get("current_progress", 0)
        target = active.get("target_count", 1)

        diff_name = rewards.get("difficulty_name", rewards.get("difficulty", "未知"))
        desc = rewards.get("description", "")
        complete_hint = "/宗门 悬赏 完成" if scope == "sect" else "/完成悬赏"

        return True, (
            f"📜 当前悬赏（{diff_name}）\n"
            f"━━━━━━━━━━━━━━━\n"
            f"任务：{active['bounty_name']}\n"
            f"说明：{desc}\n"
            f"进度：{progress}/{target}\n"
            f"奖励：{rewards.get('stone', 0):,} 灵石 + {rewards.get('exp', 0):,} 修为\n"
            f"剩余时间：{remaining // 60} 分钟\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 完成后使用 {complete_hint} 领取奖励"
        )

    async def complete_bounty(
        self, player: Player, scope: str = "global"
    ) -> tuple[bool, str]:
        """Settle a finished bounty transactionally (stone/exp into players, status -> done), then roll item drops into the storage ring (best-effort)."""
        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if not active:
                await self.db.conn.rollback()
                return False, "你当前没有进行中的悬赏任务。"

            mismatch = self._scope_mismatch_message(
                self._active_bounty_is_sect(active),
                scope,
                "完成悬赏",
                "完成",
            )
            if mismatch:
                await self.db.conn.rollback()
                return False, mismatch

            if int(time.time()) > active["expire_time"]:
                await self.db.conn.execute(
                    "UPDATE bounty_tasks SET status = 0 WHERE user_id = ? AND status = 1",
                    (player.user_id,),
                )
                await self.db.conn.commit()
                return False, "悬赏任务已超时，自动取消。"

            progress = active.get("current_progress", 0)
            target = active.get("target_count", 1)
            if progress < target:
                await self.db.conn.rollback()
                return False, (
                    f"❌ 任务尚未完成！\n"
                    f"任务：{active['bounty_name']}\n"
                    f"进度：{progress}/{target}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"💡 通过历练或秘境推进悬赏进度"
                )

            rewards = json.loads(active["rewards"])
            stone_reward = rewards.get("stone", 0)
            exp_reward = rewards.get("exp", 0)

            await self.db.conn.execute(
                "UPDATE bounty_tasks SET status = 2 WHERE user_id = ? AND status = 1",
                (player.user_id,),
            )

            MAX_VALUE = 2**63 - 1
            player.gold = min(player.gold + stone_reward, MAX_VALUE)
            player.experience = min(player.experience + exp_reward, MAX_VALUE)
            await self.db.conn.execute(
                "UPDATE players SET gold = ?, experience = ? WHERE user_id = ?",
                (player.gold, player.experience, player.user_id),
            )
            await self.db.conn.commit()
        except Exception:
            await self.db.conn.rollback()
            raise

        item_msg = ""
        if self.storage_ring_manager:
            try:
                rewards = json.loads(active["rewards"])
                item_table = rewards.get("item_table") or active.get(
                    "target_type", "gather"
                )
                dropped_items = await self._roll_bounty_items(player, item_table)
                if dropped_items:
                    lines = []
                    for item_name, count in dropped_items:
                        success, _ = await self.storage_ring_manager.store_item(
                            player, item_name, count, silent=True
                        )
                        if success:
                            lines.append(f"  · {item_name} x{count}")
                        else:
                            lines.append(
                                f"  · {item_name} x{count}（储物戒已满，丢失）"
                            )
                    if lines:
                        item_msg = "\n\n📦 获得物品：\n" + "\n".join(lines)
            except Exception:
                logger.warning("悬赏物品奖励发放异常", exc_info=True)

        rewards = json.loads(active["rewards"])
        diff_name = rewards.get("difficulty_name", rewards.get("difficulty", "未知"))
        return True, (
            f"✅ 悬赏完成（{diff_name}）！\n"
            f"任务：{active['bounty_name']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"获得灵石：+{rewards.get('stone', 0):,}\n"
            f"获得修为：+{rewards.get('exp', 0):,}{item_msg}"
        )

    async def abandon_bounty(
        self, player: Player, scope: str = "global"
    ) -> tuple[bool, str]:
        """Cancel the active bounty and set a 30-minute re-accept cooldown in system_config (scope 分流：跨类型引导到对方入口)。"""
        active = await self.db.ext.get_active_bounty(player.user_id)
        if not active:
            return False, "你当前没有进行中的悬赏任务。"

        mismatch = self._scope_mismatch_message(
            self._active_bounty_is_sect(active),
            scope,
            "放弃悬赏",
            "放弃",
        )
        if mismatch:
            return False, mismatch
        await self.db.ext.cancel_bounty(player.user_id)
        abandon_cooldown = int(time.time()) + 1800
        await self.db.ext.set_system_config(
            f"bounty_abandon_cd_{player.user_id}", str(abandon_cooldown)
        )
        return True, f"已放弃悬赏：{active['bounty_name']}\n⚠️ 30分钟内无法接取新悬赏"

    # -------- 进度与奖励 --------

    async def _roll_bounty_items(
        self, player: Player, table_name: str
    ) -> list[tuple[str, int]]:
        """70% chance weighted roll of one item stack from the bounty's item table."""
        dropped_items: list[tuple[str, int]] = []
        drop_table = self.item_tables.get(
            table_name, self.item_tables.get("gather", [])
        )
        if not drop_table or random.randint(1, 100) > 70:
            return dropped_items

        total_weight = sum(item["weight"] for item in drop_table)
        roll = random.randint(1, total_weight)
        upto = 0
        chosen = drop_table[0]
        for item in drop_table:
            upto += item["weight"]
            if roll <= upto:
                chosen = item
                break

        count = random.randint(chosen["min"], chosen["max"])
        dropped_items.append((chosen["name"], count))
        return dropped_items

    async def add_bounty_progress(
        self, player: Player, activity_tag: str, count: int = 1
    ) -> tuple[bool, str]:
        """根据活动标签推进悬赏"""
        if not isinstance(count, int) or count <= 0:
            return False, ""
        count = min(count, 10)
        activity_tag = (activity_tag or "").strip().lower()
        if not activity_tag:
            return False, ""

        await self.db.conn.execute("BEGIN IMMEDIATE")
        try:
            active = await self.db.ext.get_active_bounty(player.user_id)
            if not active:
                await self.db.conn.rollback()
                return False, ""

            if int(time.time()) > active["expire_time"]:
                await self.db.conn.rollback()
                return False, ""

            rewards_data = {}
            try:
                rewards_data = json.loads(active["rewards"])
            except Exception:
                rewards_data = {}

            template = self.templates_by_id.get(active["bounty_id"])
            if template:
                allowed_tags = template.get("progress_tags", [])
            else:
                allowed_tags = [
                    str(tag).lower() for tag in rewards_data.get("progress_tags", [])
                ]

            if activity_tag not in allowed_tags:
                await self.db.conn.rollback()
                return False, ""

            progress = active.get("current_progress", 0)
            target = active.get("target_count", 1)
            if progress >= target:
                await self.db.conn.rollback()
                return False, ""

            new_progress = min(target, progress + count)
            await self.db.conn.execute(
                "UPDATE bounty_tasks SET current_progress = ? WHERE user_id = ? AND status = 1 AND current_progress = ?",
                (new_progress, player.user_id, progress),
            )
            await self.db.conn.commit()

            if new_progress >= target:
                # 完成提示按悬赏类型指向对应入口（宗门悬赏走 /宗门 悬赏 完成）
                complete_cmd = (
                    "/宗门 悬赏 完成"
                    if template and template.get("sect_id")
                    else "/完成悬赏"
                )
                return (
                    True,
                    f"\n\n📜 悬赏【{active['bounty_name']}】已完成！使用 {complete_cmd} 领取奖励",
                )
            return True, f"\n\n📜 悬赏进度：{new_progress}/{target}"
        except Exception:
            await self.db.conn.rollback()
            raise

    async def check_and_expire_bounties(self) -> int:
        """Mark overdue active bounties as expired (status 3). Entry point of the scheduled expiry task."""
        now = int(time.time())
        cursor = await self.db.conn.execute(
            "UPDATE bounty_tasks SET status = 3 WHERE status = 1 AND expire_time < ?",
            (now,),
        )
        await self.db.conn.commit()
        return cursor.rowcount
