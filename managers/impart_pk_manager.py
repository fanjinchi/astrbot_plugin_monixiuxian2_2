"""传承PK系统管理器"""

import random

from ..data import DataBase
from ..models import Player
from .combat_manager import CombatEngine, CombatManager

__all__ = ["ImpartPkManager"]


class ImpartPkManager:
    """传承PK管理器 - 玩家间争夺传承的战斗"""

    def __init__(self, db: DataBase, combat_mgr: CombatManager):
        self.db = db
        self.combat_mgr = combat_mgr

    async def challenge_impart(
        self, attacker: Player, defender: Player
    ) -> tuple[bool, str, dict]:
        """发起传承挑战

        Args:
            attacker: 挑战者
            defender: 被挑战者

        Returns:
            (attacker_wins, battle_log, rewards)
        """
        # 获取双方传承等级
        attacker_impart = await self.db.ext.get_impart_info(attacker.user_id)
        defender_impart = await self.db.ext.get_impart_info(defender.user_id)

        # Use the unified combat engine
        engine: CombatEngine = self.combat_mgr.engine
        f1 = engine.build_fighter_from_player(attacker, is_attacker=True)
        f2 = engine.build_fighter_from_player(defender, is_attacker=False)

        result = engine.resolve_combat(f1, f2, combat_type="impart_pk")

        # 判定胜负
        attacker_wins = result.winner == attacker.user_id

        rewards = {}
        if attacker_wins:
            # 胜利奖励：获得传承加成
            impart_gain = random.uniform(0.01, 0.05)  # 1%-5%
            if attacker_impart:
                new_atk_per = min(1.0, attacker_impart.impart_atk_per + impart_gain)
                attacker_impart.impart_atk_per = new_atk_per
                await self.db.ext.update_impart_info(attacker_impart)
                rewards["impart_atk_gain"] = impart_gain

            # 失败惩罚
            if defender_impart and defender_impart.impart_atk_per > 0:
                loss = min(impart_gain / 2, defender_impart.impart_atk_per)
                defender_impart.impart_atk_per -= loss
                await self.db.ext.update_impart_info(defender_impart)
                rewards["defender_loss"] = loss
        else:
            # 失败惩罚：损失修为
            exp_loss = int(attacker.experience * 0.01)  # 1%
            attacker.experience = max(0, attacker.experience - exp_loss)
            await self.db.update_player(attacker)
            rewards["exp_loss"] = exp_loss

        # Return merged log (last chunk if multiple)
        battle_text = result.combat_log[-1] if result.combat_log else "战斗结束"
        return attacker_wins, battle_text, rewards

    async def get_impart_ranking(self, limit: int = 10) -> list:
        """获取传承排行榜"""
        # 查询所有传承数据，按攻击加成排序
        async with self.db.conn.execute(
            """
            SELECT user_id, impart_hp_per, impart_mp_per, impart_atk_per,
                   impart_know_per, impart_burst_per
            FROM impart_info
            ORDER BY impart_atk_per DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                user_id = row[0]
                player = await self.db.get_player_by_id(user_id)
                if player:
                    total_per = row[1] + row[2] + row[3] + row[4] + row[5]
                    results.append(
                        {
                            "user_id": user_id,
                            "user_name": player.user_name or user_id[:8],
                            "atk_per": row[3],
                            "total_per": total_per,
                        }
                    )
            return results
