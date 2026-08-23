"""Impart PK system manager — snatch-based rework (v32).

传承挑战只负责夺取传承实例整体所有权：
- 挑战者胜 → 目标实例转移（传承值/已领等阶清零，需重新修炼），被夺方获得 3 日保护期
- 被挑战者胜 → 无变化
- 平局 → 不转移、不冷却
- 挑战者败 → 扣 1% 当前修为（现状惩罚）+ 5 天内不得再挑战同一目标

前置校验：目标被夺保护期、挑战者失败冷却、sect 传承不可夺、无可夺目标拒绝。
"""

from ..data import DataBase
from ..managers.impart_manager import ImpartManager
from ..models import Player
from .combat_manager import CombatEngine, CombatManager

__all__ = ["ImpartPkManager"]


def _fmt_duration(seconds: int) -> str:
    """Format seconds as a compact Chinese duration (X天X小时 / X小时 / X分钟)."""
    days, rem = divmod(seconds, 86400)
    hours, minutes = divmod(rem, 3600)
    minutes //= 60
    if days:
        return f"{days}天{hours}小时" if hours else f"{days}天"
    if hours:
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    return f"{max(1, minutes)}分钟"


class ImpartPkManager:
    """Manager for impart PK snatch challenges between players."""

    def __init__(
        self, db: DataBase, combat_mgr: CombatManager, impart_mgr: ImpartManager
    ):
        self.db = db
        self.combat_mgr = combat_mgr
        self.impart_mgr = impart_mgr

    async def challenge_impart(
        self, attacker: Player, defender: Player, legacy_type: str = ""
    ) -> tuple[bool, str, dict]:
        """Run an impart snatch challenge between two players.

        Args:
            attacker: The challenging player.
            defender: The defending player.
            legacy_type: Optional type filter (common/adventure/rift); empty
                picks the defender's most recent non-sect instance.

        Returns:
            A tuple of (attacker_wins, battle_log_or_rejection, rewards).
            On rejection, attacker_wins is False and rewards contains
            {"rejected": reason}.
        """
        # 前置校验：被夺保护期
        protection = await self.impart_mgr.get_snatch_protection_remaining(
            defender.user_id
        )
        if protection > 0:
            return (
                False,
                "",
                {
                    "rejected": (
                        f"对方刚被夺取传承，尚在保护期内"
                        f"（剩余 {_fmt_duration(protection)}），暂不可挑战。"
                    )
                },
            )

        # 前置校验：挑战者对该目标的失败冷却
        allowed, remaining = await self.impart_mgr.can_challenge(
            attacker.user_id, defender.user_id
        )
        if not allowed:
            return (
                False,
                "",
                {
                    "rejected": (
                        f"你 5 天内曾挑战对方失败，仍需冷却"
                        f"（剩余 {_fmt_duration(remaining)}）。"
                    )
                },
            )

        # 目标实例选择
        target = await self.impart_mgr.select_snatch_target(
            defender.user_id, legacy_type or None
        )
        if not target:
            if legacy_type:
                reason = (
                    f"对方没有可夺取的{self.impart_mgr.get_type_name(legacy_type)}。"
                )
            else:
                reason = "对方没有可夺取的传承（宗门传承不可通过 PK 夺取）。"
            return False, "", {"rejected": reason}

        engine: CombatEngine = self.combat_mgr.engine
        f1 = await engine.build_fighter_from_player(attacker, is_attacker=True)
        f2 = await engine.build_fighter_from_player(defender, is_attacker=False)

        result = engine.resolve_combat(f1, f2, combat_type="impart_pk")
        battle_text = result.combat_log[-1] if result.combat_log else "战斗结束"

        rewards: dict = {
            "target_instance_id": target.id,
            "target_type": target.legacy_type,
        }

        if result.winner == "draw":
            rewards["draw"] = True
            return False, battle_text, rewards

        attacker_wins = result.winner == attacker.user_id
        if attacker_wins:
            transferred = await self.impart_mgr.transfer_legacy(
                target.id, attacker.user_id, expected_owner=defender.user_id
            )
            if transferred is None:
                # 并发场景：实例在战斗期间已被他人转移（归属重校验不过）
                return (
                    False,
                    battle_text,
                    {"rejected": "你慢了一步：对方的那条传承已被他人夺走。"},
                )
            # 被夺方获得 3 日保护期（任何玩家不可挑战）
            await self.impart_mgr.record_snatch_protection(defender.user_id)
            rewards["snatched_type"] = target.legacy_type
            return True, battle_text, rewards

        # 挑战者失败：1% 修为惩罚 + 5 天同人冷却
        exp_loss = int(attacker.experience * 0.01)
        attacker.experience = max(0, attacker.experience - exp_loss)
        await self.db.update_player(attacker)
        await self.impart_mgr.record_challenge_failure(
            attacker.user_id, defender.user_id
        )
        rewards["exp_loss"] = exp_loss
        return False, battle_text, rewards

    async def get_impart_ranking(self, limit: int = 10) -> list[dict]:
        """Return the top players by total impart value across instances."""
        rankings = await self.impart_mgr.get_ranking(limit)
        results = []
        for row in rankings:
            player = await self.db.get_player_by_id(row["user_id"])
            if player:
                results.append(
                    {
                        "user_id": row["user_id"],
                        "user_name": player.user_name or row["user_id"][:8],
                        "impart_value": row["impart_value"],
                    }
                )
        return results
