# managers/blessed_land_manager.py
"""洞天福地系统管理器"""

import time

from ..data import DataBase
from ..models import Player

__all__ = ["BlessedLandManager"]

# 洞天配置
BLESSED_LANDS = {
    1: {
        "name": "小洞天",
        "price": 10000,
        "exp_bonus": 0.05,
        "gold_per_hour": 100,
        "max_level": 5,
        "max_exp_per_hour": 5000,
    },
    2: {
        "name": "中洞天",
        "price": 50000,
        "exp_bonus": 0.10,
        "gold_per_hour": 500,
        "max_level": 10,
        "max_exp_per_hour": 15000,
    },
    3: {
        "name": "大洞天",
        "price": 200000,
        "exp_bonus": 0.20,
        "gold_per_hour": 2000,
        "max_level": 15,
        "max_exp_per_hour": 30000,
    },
    4: {
        "name": "福地",
        "price": 500000,
        "exp_bonus": 0.30,
        "gold_per_hour": 5000,
        "max_level": 20,
        "max_exp_per_hour": 50000,
    },
    5: {
        "name": "洞天福地",
        "price": 1000000,
        "exp_bonus": 0.50,
        "gold_per_hour": 10000,
        "max_level": 30,
        "max_exp_per_hour": 100000,
    },
}


class BlessedLandManager:
    """洞天福地管理器"""

    def __init__(self, db: DataBase):
        self.db = db

    async def get_user_blessed_land(self, user_id: str) -> dict | None:
        """获取用户洞天信息"""
        async with self.db.conn.execute(
            "SELECT * FROM blessed_lands WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def purchase_blessed_land(
        self, player: Player, land_type: int
    ) -> tuple[bool, str]:
        """购买洞天"""
        if land_type not in BLESSED_LANDS:
            return (
                False,
                "❌ 无效的洞天类型。可选：1-小洞天 2-中洞天 3-大洞天 4-福地 5-洞天福地",
            )

        # 检查是否已有洞天
        existing = await self.get_user_blessed_land(player.user_id)
        if existing:
            return (
                False,
                f"❌ 你已拥有【{existing['land_name']}】，请先升级而非重新购买。",
            )

        land_config = BLESSED_LANDS[land_type]
        price = land_config["price"]

        if player.gold < price:
            return False, f"❌ 灵石不足！购买{land_config['name']}需要 {price:,} 灵石。"

        # 扣费与建洞天必须同生共死：分开提交时扣费已落库、建洞天失败会重复扣费。
        # CM 单事务——正常退出整体提交，任何失败整体回滚（全有或全无）
        async with self.db.transaction():
            # 写锁内重读 + 复核（bd -546）：余额与「是否已有洞天」都以最新行为准，
            # 避免入口快照在并发窗口里重复扣费 / 重复建洞天。
            fresh = await self.db.get_player_by_id(player.user_id)
            if fresh is None:
                return False, "❌ 玩家不存在或已被删除。"
            existing = await self.get_user_blessed_land(player.user_id)
            if existing:
                return (
                    False,
                    f"❌ 你已拥有【{existing['land_name']}】，请先升级而非重新购买。",
                )
            if fresh.gold < price:
                return (
                    False,
                    f"❌ 灵石不足！购买{land_config['name']}需要 {price:,} 灵石。",
                )
            fresh.gold -= price
            await self.db.update_player(fresh)

            # 创建洞天
            await self.db.conn.execute(
                """
                INSERT INTO blessed_lands (user_id, land_type, land_name, level, exp_bonus,
                                           gold_per_hour, last_collect_time)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    player.user_id,
                    land_type,
                    land_config["name"],
                    land_config["exp_bonus"],
                    land_config["gold_per_hour"],
                    int(time.time()),
                ),
            )
        # 块内原裸 conn.commit() 随 CM 转换删除（owner 层统一提交）
        player.gold = fresh.gold  # 内存对齐最新账本，供调用方后续渲染

        return True, (
            f"✨ 恭喜获得【{land_config['name']}】！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{land_config['exp_bonus']:.0%}\n"
            f"每小时产出：{land_config['gold_per_hour']} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"使用 /洞天收取 领取产出"
        )

    async def upgrade_blessed_land(self, player: Player) -> tuple[bool, str]:
        """升级洞天"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！使用 /购买洞天 <类型> 获取。"

        land_type = land["land_type"]
        current_level = land["level"]
        config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])

        if current_level >= config["max_level"]:
            return (
                False,
                f"❌ 你的{land['land_name']}已达最高等级 {config['max_level']}！",
            )

        # 升级费用：基础价格 × 当前等级 × 0.5
        upgrade_cost = int(config["price"] * current_level * 0.5)

        if player.gold < upgrade_cost:
            return False, f"❌ 灵石不足！升级需要 {upgrade_cost:,} 灵石。"

        # 扣费与升级必须同生共死：分开提交时扣费已落库、升级失败会重复扣费。
        # CM 单事务——正常退出整体提交，任何失败整体回滚（全有或全无）
        async with self.db.transaction():
            # 写锁内重读 + 复核（bd -546）：等级与余额都取最新行——并发双击不会
            # 互相覆盖等级，也不会按过期快照重复扣费。
            land = await self.get_user_blessed_land(player.user_id)
            fresh = await self.db.get_player_by_id(player.user_id)
            if not land or fresh is None:
                return False, "❌ 你还没有洞天！使用 /购买洞天 <类型> 获取。"
            land_type = land["land_type"]
            current_level = land["level"]
            config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
            if current_level >= config["max_level"]:
                return (
                    False,
                    f"❌ 你的{land['land_name']}已达最高等级 {config['max_level']}！",
                )
            # 升级费用：基础价格 × 当前等级 × 0.5
            upgrade_cost = int(config["price"] * current_level * 0.5)
            if fresh.gold < upgrade_cost:
                return False, f"❌ 灵石不足！升级需要 {upgrade_cost:,} 灵石。"
            # 升级加成
            new_level = current_level + 1
            new_exp_bonus = config["exp_bonus"] * (1 + new_level * 0.1)
            new_gold_per_hour = int(config["gold_per_hour"] * (1 + new_level * 0.15))
            fresh.gold -= upgrade_cost
            await self.db.update_player(fresh)

            await self.db.conn.execute(
                """
                UPDATE blessed_lands SET level = ?, exp_bonus = ?, gold_per_hour = ?
                WHERE user_id = ?
                """,
                (new_level, new_exp_bonus, new_gold_per_hour, player.user_id),
            )
        # 块内原裸 conn.commit() 随 CM 转换删除（owner 层统一提交）
        player.gold = fresh.gold  # 内存对齐最新账本

        return True, (
            f"🎉 {land['land_name']}升级到 Lv.{new_level}！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{new_exp_bonus:.1%}\n"
            f"每小时产出：{new_gold_per_hour} 灵石\n"
            f"花费：{upgrade_cost:,} 灵石"
        )

    async def collect_income(self, player: Player) -> tuple[bool, str]:
        """收取洞天产出"""
        land = await self.get_user_blessed_land(player.user_id)
        if not land:
            return False, "❌ 你还没有洞天！"

        last_collect = land["last_collect_time"]
        now = int(time.time())
        hours_passed = (now - last_collect) / 3600

        if hours_passed < 1:
            remaining = int(3600 - (now - last_collect))
            minutes = remaining // 60
            return False, f"❌ 收取冷却中，还需 {minutes} 分钟。"

        # 发产出与推进领取时间戳必须同生共死：分开提交时收益已落库、时间戳未推进
        # 会让玩家重复领取同一段产出。CM 单事务（全有或全无）
        async with self.db.transaction():
            # 写锁内重读 + 复核（bd -546）：洞天行与玩家行都在写锁内重取——并发
            # 双击时只有先拿到写锁的那一路能领，后到者读取的 last_collect_time
            # 已被推进、hours < 1 直接拒绝，收益不会按同一窗口发两遍。
            land = await self.get_user_blessed_land(player.user_id)
            fresh = await self.db.get_player_by_id(player.user_id)
            if not land or fresh is None:
                return False, "❌ 你还没有洞天！"
            now = int(time.time())
            hours_passed = (now - land["last_collect_time"]) / 3600
            if hours_passed < 1:
                remaining = int(3600 - (now - land["last_collect_time"]))
                return False, f"❌ 收取冷却中，还需 {remaining // 60} 分钟。"

            # 计算产出（最多24小时）
            hours = min(24, int(hours_passed))
            gold_income = land["gold_per_hour"] * hours

            # 计算修为收益，并限制上限防止高修为玩家收益无限增长
            land_type = land["land_type"]
            config = BLESSED_LANDS.get(land_type, BLESSED_LANDS[1])
            max_exp_per_hour = config.get("max_exp_per_hour", 5000)
            exp_income = int(fresh.experience * land["exp_bonus"] * hours * 0.01)
            exp_income = min(exp_income, max_exp_per_hour * hours)

            fresh.gold += gold_income
            fresh.experience += exp_income
            await self.db.update_player(fresh)

            await self.db.conn.execute(
                "UPDATE blessed_lands SET last_collect_time = ? WHERE user_id = ?",
                (now, fresh.user_id),
            )
        # 块内原裸 conn.commit() 随 CM 转换删除（owner 层统一提交）
        player.gold = fresh.gold  # 内存对齐最新账本
        player.experience = fresh.experience

        return True, (
            f"✅ 洞天收取成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"累计时长：{hours} 小时\n"
            f"获得灵石：+{gold_income:,}\n"
            f"获得修为：+{exp_income:,}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"当前灵石：{player.gold:,}"
        )

    async def get_blessed_land_info(self, user_id: str) -> str:
        """获取洞天信息展示"""
        land = await self.get_user_blessed_land(user_id)
        if not land:
            return (
                "🏔️ 洞天福地\n"
                "━━━━━━━━━━━━━━━\n"
                "你还没有洞天！\n\n"
                "可购买的洞天：\n"
                "  1. 小洞天 - 10,000灵石\n"
                "  2. 中洞天 - 50,000灵石\n"
                "  3. 大洞天 - 200,000灵石\n"
                "  4. 福地 - 500,000灵石\n"
                "  5. 洞天福地 - 1,000,000灵石\n\n"
                "💡 使用 /购买洞天 <编号>"
            )

        now = int(time.time())
        hours_since = (now - land["last_collect_time"]) / 3600
        pending_gold = int(min(24, hours_since) * land["gold_per_hour"])

        return (
            f"🏔️ {land['land_name']} (Lv.{land['level']})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"修炼加成：+{land['exp_bonus']:.1%}\n"
            f"每小时产出：{land['gold_per_hour']} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"待收取：约 {pending_gold:,} 灵石\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 /升级洞天 | /洞天收取"
        )
