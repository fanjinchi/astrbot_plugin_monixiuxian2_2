"""Impart PK system manager."""

import random

from ..data import DataBase
from ..managers.impart_manager import ImpartManager
from ..models import Player
from .combat_manager import CombatEngine, CombatManager

__all__ = ["ImpartPkManager"]


class ImpartPkManager:
    """Manager for impart PK challenges between players."""

    def __init__(
        self, db: DataBase, combat_mgr: CombatManager, impart_mgr: ImpartManager
    ):
        self.db = db
        self.combat_mgr = combat_mgr
        self.impart_mgr = impart_mgr

    async def challenge_impart(
        self, attacker: Player, defender: Player
    ) -> tuple[bool, str, dict]:
        """Run an impart challenge between two players.

        Args:
            attacker: The challenging player.
            defender: The defending player.

        Returns:
            A tuple of (attacker_wins, battle_log, rewards).
        """
        engine: CombatEngine = self.combat_mgr.engine
        f1 = await engine.build_fighter_from_player(attacker, is_attacker=True)
        f2 = await engine.build_fighter_from_player(defender, is_attacker=False)

        result = engine.resolve_combat(f1, f2, combat_type="impart_pk")
        attacker_wins = result.winner == attacker.user_id

        rewards = {}
        if attacker_wins:
            gain = random.randint(1, 5)
            await self.impart_mgr.add_impart_value(attacker.user_id, gain)
            rewards["impart_value_gain"] = gain
        else:
            exp_loss = int(attacker.experience * 0.01)
            attacker.experience = max(0, attacker.experience - exp_loss)
            await self.db.update_player(attacker)
            rewards["exp_loss"] = exp_loss

        battle_text = result.combat_log[-1] if result.combat_log else "战斗结束"
        return attacker_wins, battle_text, rewards

    async def get_impart_ranking(self, limit: int = 10) -> list[dict]:
        """Return the top players by impart value."""
        async with self.db.conn.execute(
            """
            SELECT user_id, impart_value
            FROM impart_info
            ORDER BY impart_value DESC
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
                    results.append(
                        {
                            "user_id": user_id,
                            "user_name": player.user_name or user_id[:8],
                            "impart_value": row[1],
                        }
                    )
            return results
