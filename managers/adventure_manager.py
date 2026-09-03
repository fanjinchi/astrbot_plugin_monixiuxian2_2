# managers/adventure_manager.py
"""
历练系统管理器 - 可配置路线、风险与奖励
"""

import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import logger

try:
    from ..core.encounter_store import KIND_LEGACY, EncounterStore
    from ..data.data_manager import DataBase
    from ..data.default_configs import ADVENTURE_CONFIG
    from ..managers.pve_combat_manager import PVECombatManager
    from ..models import Player
    from ..models_extended import UserStatus
    from ..utils.narrative_text import select_narrative_pool
except ImportError:
    # 独立运行（测试）时降级加载依赖
    def _load_module(name, rel_path):
        """Import a plugin module by file path so this file can run standalone under tests."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def _load_default_configs():
        """Load data/default_configs.py under a synthetic package.

        default_configs relatively imports its narrative_defaults package, so
        the plain file-path loader above cannot satisfy it; a synthetic parent
        package gives the relative import a resolution context.
        """
        import types

        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pkg_name = "adventure_manager_standalone_data"
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [os.path.join(plugin_root, "data")]
            sys.modules[pkg_name] = pkg
        full_name = f"{pkg_name}.default_configs"
        if full_name in sys.modules:
            return sys.modules[full_name]
        path = os.path.join(plugin_root, "data", "default_configs.py")
        spec = importlib.util.spec_from_file_location(full_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        return mod

    DataBase = object
    _pve = _load_module("pve_combat_manager", "managers/pve_combat_manager.py")
    PVECombatManager = _pve.PVECombatManager
    _md = _load_module("models", "models.py")
    Player = _md.Player
    _mde = _load_module("models_extended", "models_extended.py")
    UserStatus = _mde.UserStatus
    _nt = _load_module("narrative_text", "utils/narrative_text.py")
    select_narrative_pool = _nt.select_narrative_pool
    ADVENTURE_CONFIG = _load_default_configs().ADVENTURE_CONFIG
    _es = _load_module("encounter_store", "core/encounter_store.py")
    EncounterStore = _es.EncounterStore
    KIND_LEGACY = _es.KIND_LEGACY

if TYPE_CHECKING:
    from ..core import StorageRingManager


class AdventureManager:
    """历练系统管理器"""

    # 宗门专属事件组追加进路线抽取池时使用的固定权重
    SECT_EVENT_GROUP_WEIGHT = 15

    CONFIG_FILE = (
        Path(__file__).resolve().parents[1] / "config" / "adventure_config.json"
    )
    # fallback 默认值单源在 data/default_configs.py（externalize-narrative-texts
    # D4 收敛，消除内嵌副本与 config 文件的漂移）
    DEFAULT_CONFIG = ADVENTURE_CONFIG

    def __init__(
        self,
        db: DataBase,
        storage_ring_manager: "StorageRingManager" = None,
        pve_combat_mgr: PVECombatManager = None,
        impart_mgr=None,
        config_manager=None,
        encounter_store=None,
    ):
        self.db = db
        self.storage_ring_manager = storage_ring_manager
        self.pve_combat_mgr = pve_combat_mgr
        # 传承管理器：可选注入（main.py 装配后），用于历练触发传承机缘
        self.impart_mgr = impart_mgr
        # 配置管理器：可选注入（当前仅保留接口位；叙事选择走模块级 select_narrative_pool）
        self.config_manager = config_manager
        # 遭遇存储：可选注入共享单例（main.py 装配，与 RiftManager 共用，
        # design D8）；默认自建，保证既有测试/独立使用不炸
        self.encounter_store = (
            encounter_store if encounter_store is not None else EncounterStore()
        )
        self._route_cooldowns: dict[str, dict[str, int]] = {}
        self.routes: dict[str, dict] = {}
        self.route_alias_index: dict[str, str] = {}
        self.event_groups: dict[str, list[dict]] = {}
        self.drop_tables: dict[str, list[dict]] = {}
        self.default_route_key: str = "scout"
        # 传承机缘触发概率与传承类型（config 顶层 legacy_chance/legacy_type）
        self.legacy_chance: float = 0.0
        self.legacy_type: str = "adventure"
        self.reload_config()

    # -------- 配置加载 --------

    def reload_config(self):
        """重新加载配置文件"""
        config = self._load_config_file()
        self.routes = {route["key"]: route for route in config.get("routes", [])}
        self.default_route_key = next(iter(self.routes.keys()), "scout")
        self.legacy_chance = float(config.get("legacy_chance", 0.0))
        self.legacy_type = config.get("legacy_type", "adventure")

        self.route_alias_index = {}
        for key, route in self.routes.items():
            aliases = set(route.get("aliases", []))
            aliases.add(route["key"])
            aliases.add(route["name"])
            # 兼容旧指令
            if route["key"] == "scout":
                aliases.update({"short", "短途"})
            elif route["key"] == "journey":
                aliases.update({"medium", "中途"})
            elif route["key"] == "peril":
                aliases.update({"long", "长途"})
            for alias in aliases:
                self.route_alias_index[alias.lower()] = key

        self.event_groups = config.get(
            "event_groups", self.DEFAULT_CONFIG["event_groups"]
        )
        self.drop_tables = config.get("drop_tables", self.DEFAULT_CONFIG["drop_tables"])

    def _load_config_file(self) -> dict:
        """加载配置文件并在失败时回退到默认配置"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("已加载 adventure_config.json")
                    return data
            except Exception as exc:
                logger.error(f"加载 adventure_config.json 失败，将使用默认配置: {exc}")
        return self.DEFAULT_CONFIG

    def get_route_overview(self) -> list[dict]:
        """暴露给指令层的路线概览"""
        overview = []
        for route in self.routes.values():
            overview.append(
                {
                    "key": route["key"],
                    "name": route["name"],
                    "risk": route.get("risk", "未知"),
                    "duration": route.get("duration", 0),
                    "min_level": route.get("min_level", 0),
                    "description": route.get("description", ""),
                }
            )
        return overview

    # -------- 核心流程 --------

    async def start_adventure(
        self, user_id: str, route_token: str = ""
    ) -> tuple[bool, str]:
        """开始指定路线的历练"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！"

        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd:
            await self.db.ext.create_user_cd(user_id)
            user_cd = await self.db.ext.get_user_cd(user_id)

        if user_cd.type != UserStatus.IDLE:
            return (
                False,
                f"❌ 你当前正{UserStatus.get_name(user_cd.type)}，无法开始历练！",
            )

        route_key = self._resolve_route(route_token)
        route = self.routes.get(route_key)
        if not route:
            return False, "❌ 未找到对应的历练路线，请先发送 /历练信息 查看可选路线。"

        if player.level_index < route.get("min_level", 0):
            return False, "❌ 你的境界还不足以踏上这条路线，先提升境界吧！"

        cooldown_end = self._route_cooldowns.get(user_id, {}).get(route_key, 0)
        now = int(time.time())
        if cooldown_end > now:
            remaining = cooldown_end - now
            minutes = remaining // 60 or 1
            return False, f"⚠️ 该路线尚在休整中，请 {minutes} 分钟后再试。"

        duration = route.get("duration", 3600)
        scheduled_time = now + duration
        extra = {"route_key": route_key}
        await self.db.ext.set_user_busy(
            user_id, UserStatus.ADVENTURING, scheduled_time, extra_data=extra
        )

        fatigue = route.get("fatigue_cooldown", 0)
        hint = [
            f"✨ 你选择了「{route['name']}」——{route.get('description', '未知冒险')}",
            f"路线风险：{route.get('risk', '未知')} | 历练时长：{duration // 60} 分钟",
        ]
        if route.get("min_level", 0):
            hint.append(f"建议境界：{route['min_level']} 阶以上")
        if fatigue:
            hint.append(f"（该路线完成后需要休整 {fatigue // 60} 分钟）")

        return True, "\n".join(hint)

    async def finish_adventure(self, user_id: str) -> tuple[bool, str, dict | None]:
        """结算历练"""
        player = await self.db.get_player_by_id(user_id)
        if not player:
            return False, "❌ 你还未踏入修仙之路！", None

        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 你当前不在历练中！", None

        now = int(time.time())
        if now < user_cd.scheduled_time:
            remaining = user_cd.scheduled_time - now
            minutes = remaining // 60
            seconds = remaining % 60
            return False, f"❌ 历练尚未完成！还需 {minutes}分{seconds}秒。", None

        extra = {}
        if hasattr(user_cd, "get_extra_data"):
            extra = user_cd.get_extra_data()
        else:
            try:
                extra = json.loads(getattr(user_cd, "extra_data", "{}") or "{}")
            except Exception:
                extra = {}

        route = self.routes.get(
            extra.get("route_key", self.default_route_key)
        ) or self.routes.get(self.default_route_key)
        if not route:
            return False, "❌ 未找到历练路线配置，请联系管理员。", None

        adventure_duration = now - user_cd.create_time
        scheduled_duration = max(1, user_cd.scheduled_time - user_cd.create_time)
        effective_duration = min(adventure_duration, scheduled_duration)
        faction_id = await self._get_player_faction_id(player)
        event = self._trigger_route_event(route, faction_id)

        combat_msg = ""
        combat_result = None
        base_rewards = self._calculate_rewards(player, route, effective_duration, event)
        if self.pve_combat_mgr:
            risk_map = {"低": "low", "中": "mid", "高": "high", "极高": "extreme"}
            difficulty = risk_map.get(route.get("risk", "低"), "low")
            combat_result = await self.pve_combat_mgr.trigger_pve_combat(
                player, "adventure", difficulty, base_rewards
            )
            if combat_result:
                combat_msg = combat_result[0]
                rewards = combat_result[1]
                if rewards.get("hp_penalty"):
                    player.hp = 1
            else:
                rewards = base_rewards
        else:
            rewards = base_rewards

        if not rewards.get("hp_penalty"):
            dropped_items, item_msg = await self._handle_drops(player, route, event)
        else:
            dropped_items, item_msg = [], ""

        # 传承机缘：按概率挂起传承之地 pending 遭遇（应邀制，不再内联挑战）。
        # 可选概率功能：异常降级为日志，绝不中断历练正常结算（防卡 ADVENTURING 状态）
        legacy_msg = ""
        if self.impart_mgr and self.legacy_chance > 0:
            try:
                legacy_msg = await self._maybe_trigger_legacy(player)
            except Exception as exc:
                logger.error(f"历练传承机缘触发失败: {exc}")

        player.experience += rewards.get("exp", 0)
        if rewards.get("bonus_exp", 0) > 0:
            player.experience += rewards["bonus_exp"]
        player.gold += rewards.get("gold", 0)
        await self.db.update_player(player)
        await self.db.ext.set_user_free(user_id)

        fatigue = route.get("fatigue_cooldown", 0)
        if event.get("injury"):
            fatigue += 600
        if combat_result and rewards.get("hp_penalty"):
            fatigue += 600
        if fatigue:
            self._route_cooldowns.setdefault(user_id, {})[route["key"]] = (
                int(time.time()) + fatigue
            )

        fatigue_hint = f"\n⏳ 该路线休整：{fatigue // 60} 分钟" if fatigue else ""
        display_minutes = effective_duration // 60
        # 事件文案：按玩家境界段从 desc_variants 分桶池取（当前段+通用桶合并随机，
        # design D7），未配置或合并池为空时逐字回落 desc 兜底
        event_desc = self._select_event_desc(event, player)
        # 宗门专属事件（带 sect_id）在结算消息中显性标记，普通事件文案不变
        event_line = event_desc
        if event.get("sect_id"):
            event_line = f"🏯 宗门际遇 · {event.get('name', '')}\n{event_desc}"
        msg = (
            f"🚶 历练归来 · {route['name']}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{event_line}"
            f"{combat_msg}\n\n"
            f"本次历练：{display_minutes} 分钟\n"
            f"获得修为：+{rewards['exp']:,}\n"
            f"获得灵石：+{rewards['gold']:,}"
            f"{item_msg}"
            f"{legacy_msg}"
            f"\n━━━━━━━━━━━━━━━\n"
            f"当前修为：{player.experience:,}\n"
            f"当前灵石：{player.gold:,}"
            f"{fatigue_hint}"
        )

        reward_data = {
            "route_key": route["key"],
            "route_name": route["name"],
            "event_key": event.get("key"),
            "event_desc": event_desc,
            "exp_reward": rewards["exp"],
            "gold_reward": rewards["gold"],
            "items": dropped_items,
            "duration": effective_duration,
            "bounty_tag": route.get("bounty_tag", "adventure"),
            "bounty_progress": max(
                1, route.get("bounty_progress", 1) + event.get("bonus_progress", 0)
            ),
            "pve_won": bool(rewards.get("pve_won", False)),
        }
        return True, msg, reward_data

    async def _maybe_trigger_legacy(self, player: Player) -> str:
        """按配置概率触发传承机缘：挂起传承之地 pending 遭遇（应邀制，design D8）。

        不再内联挑战守护者；玩家经「探索秘境 传承」应邀（探索秘境为遭遇响应
        枢纽，含历练来源——命名取舍见 design D8）。

        Returns:
            追加到结算消息的提示文本（未触发时为空串）。
        """
        if random.random() >= self.legacy_chance:
            return ""
        if self.encounter_store is None:
            return ""
        # TTL 不显式传：用 store 默认值——装配时（main.py）已注入
        # encounter_ttl_seconds 配置值，历练/秘境两条路径时限语义一致
        self.encounter_store.pend(
            player.user_id,
            KIND_LEGACY,
            {"legacy_type": self.legacy_type, "source": "adventure"},
        )
        # 提示文案与 RiftManager._pend_legacy_encounter 保持逐字一致
        # （两处各写一份，避免为单行文案引入跨管理器依赖）
        return (
            "\n\n🗿 你偶遇上古传承之地，传承禁制悄然开启。\n"
            "💡 发送「探索秘境 传承」应邀挑战守护者（不响应则机缘自行消散，无任何惩罚）"
        )

    async def check_adventure_status(self, user_id: str) -> tuple[bool, str]:
        """查看历练状态"""
        user_cd = await self.db.ext.get_user_cd(user_id)
        if not user_cd or user_cd.type != UserStatus.ADVENTURING:
            return False, "❌ 你当前不在历练中！"

        now = int(time.time())
        route_name = "未知路线"
        extra = {}
        if hasattr(user_cd, "get_extra_data"):
            extra = user_cd.get_extra_data()
        else:
            try:
                extra = json.loads(getattr(user_cd, "extra_data", "{}") or "{}")
            except Exception:
                extra = {}
        route = self.routes.get(extra.get("route_key", self.default_route_key))
        if route:
            route_name = route["name"]

        if now >= user_cd.scheduled_time:
            return True, f"✅ {route_name} 已完成！使用 /完成历练 领取奖励。"

        remaining = user_cd.scheduled_time - now
        elapsed = now - user_cd.create_time
        minutes = remaining // 60
        seconds = remaining % 60
        elapsed_minutes = elapsed // 60

        msg = (
            f"📍 历练进度 · {route_name}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"已历练：{elapsed_minutes} 分钟\n"
            f"剩余时间：{minutes}分{seconds}秒\n"
            f"请耐心等待历练完成..."
        )
        return True, msg

    # -------- 内部工具 --------

    def _resolve_route(self, token: str) -> str:
        """Map a user token (route key, name, or alias) to a route key, falling back to the default route."""
        if not token:
            return self.default_route_key
        normalized = token.strip().lower()
        return self.route_alias_index.get(normalized, self.default_route_key)

    async def _get_player_faction_id(self, player: Player) -> str | None:
        """Resolve the faction_id of the player's sect (None when sectless or a player-built sect)."""
        sect_id = getattr(player, "sect_id", 0)
        if not isinstance(sect_id, int) or not sect_id:
            return None
        if self.db is None or getattr(self.db, "ext", None) is None:
            return None
        sect = await self.db.ext.get_sect_by_id(sect_id)
        if sect is None:
            return None
        return getattr(sect, "faction_id", None)

    def _filter_group_events(
        self, events: list[dict], faction_id: str | None
    ) -> list[dict]:
        """Keep events with no sect attribution plus events matching the player's sect faction."""
        return [
            event
            for event in events
            if isinstance(event, dict)
            and (not event.get("sect_id") or event.get("sect_id") == faction_id)
        ]

    def _select_event_desc(self, event: dict, player: Player) -> str:
        """Pick the event's narrative copy for the player.

        ``desc_variants`` (design D7) is normalized by the shared
        ``select_narrative_pool`` helper: bucketed pools merge the player's
        current realm-segment bucket with the 通用 bucket and filter
        route-tagged entries by the player's cultivation route. An empty pool
        (no variants configured, uncovered segment, or everything filtered)
        falls back to the verbatim ``desc`` field.
        """
        pool = select_narrative_pool(
            event.get("desc_variants"),
            route=getattr(player, "cultivation_type", None),
            level_index=getattr(player, "level_index", None),
        )
        if pool:
            return random.choice(pool)
        return event["desc"]

    def _build_event_weight_pool(
        self, route: dict, faction_id: str | None
    ) -> dict[str, int]:
        """Build the effective event-group weight pool for a route and player faction.

        Groups whose events all carry a mismatched ``sect_id`` are dropped.
        Sect groups (any event carrying ``sect_id``) not referenced by the
        route are appended with ``SECT_EVENT_GROUP_WEIGHT`` when the player
        belongs to that sect.
        """
        weights: dict[str, int] = {}
        for key, weight in (route.get("event_weights", {}) or {}).items():
            group = self.event_groups.get(key)
            if group is None:
                weights[key] = weight
                continue
            if self._filter_group_events(group, faction_id):
                weights[key] = weight
        if faction_id:
            for key, events in self.event_groups.items():
                if key in weights:
                    continue
                if not any(
                    isinstance(event, dict) and event.get("sect_id") for event in events
                ):
                    continue
                if self._filter_group_events(events, faction_id):
                    weights[key] = self.SECT_EVENT_GROUP_WEIGHT
        return weights

    def _trigger_route_event(self, route: dict, faction_id: str | None = None) -> dict:
        """Weighted-random pick an event group for the route, then uniformly pick one event from it.

        Sect-attributed groups/events only enter the pool when the player's
        sect faction matches; everything else is unchanged.
        """
        weights = self._build_event_weight_pool(route, faction_id)
        if not weights:
            group_key = "standard"
        else:
            total_weight = sum(max(0, w) for w in weights.values()) or 1
            roll = random.randint(1, total_weight)
            upto = 0
            group_key = "standard"
            for key, weight in weights.items():
                upto += max(0, weight)
                if roll <= upto:
                    group_key = key
                    break

        group = (
            self.event_groups.get(group_key)
            or self.event_groups.get("standard")
            or self.DEFAULT_CONFIG["event_groups"]["standard"]
        )
        eligible = self._filter_group_events(group, faction_id)
        if not eligible:
            eligible = self._filter_group_events(
                self.event_groups.get("standard")
                or self.DEFAULT_CONFIG["event_groups"]["standard"],
                faction_id,
            )
        return random.choice(eligible)

    def _calculate_rewards(
        self, player: Player, route: dict, duration: int, event: dict
    ) -> dict[str, int]:
        """Compute exp/gold from route per-minute rates, level bonus, completion bonus, and the event multiplier."""
        duration_minutes = max(1, duration // 60)
        base_exp = duration_minutes * route.get("base_exp_per_min", 40)
        base_gold = duration_minutes * route.get("base_gold_per_min", 10)

        level_bonus_exp = player.level_index * route.get("level_bonus_exp", 10)
        level_bonus_gold = player.level_index * route.get("level_bonus_gold", 2)

        completion_bonus = route.get("completion_bonus", {})
        exp_total = base_exp + level_bonus_exp + completion_bonus.get("exp", 0)
        gold_total = base_gold + level_bonus_gold + completion_bonus.get("gold", 0)

        final_exp = max(0, int(exp_total * event.get("exp_mult", 1.0)))
        final_gold = max(0, int(gold_total * event.get("gold_mult", 1.0)))
        return {"exp": final_exp, "gold": final_gold}

    async def _handle_drops(
        self, player: Player, route: dict, event: dict
    ) -> tuple[list[tuple[str, int]], str]:
        """Roll an item drop (event item_chance) from the tier drop table and store it in the storage ring."""
        dropped_items: list[tuple[str, int]] = []
        if not self.storage_ring_manager:
            return dropped_items, ""

        item_chance = event.get("item_chance", 40)
        if random.randint(1, 100) > item_chance:
            return dropped_items, ""

        tier = event.get("drop_tier") or route.get("drop_tier") or "low"
        drop_table = self.drop_tables.get(
            tier, self.DEFAULT_CONFIG["drop_tables"]["low"]
        )
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

        item_lines = []
        for item_name, qty in dropped_items:
            success, _ = await self.storage_ring_manager.store_item(
                player, item_name, qty, silent=True
            )
            if success:
                item_lines.append(f"  · {item_name} x{qty}")
            else:
                item_lines.append(f"  · {item_name} x{qty}（储物戒已满，丢失）")

        if item_lines:
            return dropped_items, "\n\n📦 获得物品：\n" + "\n".join(item_lines)
        return dropped_items, ""
