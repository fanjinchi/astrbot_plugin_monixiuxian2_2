# handlers/ranking_handlers.py
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.ranking_manager import RankingManager


class RankingHandlers:
    """Handlers for leaderboard commands: level, power, wealth, and deposit rankings."""

    def __init__(self, db: DataBase, rank_mgr: RankingManager):
        self.db = db
        self.rank_mgr = rank_mgr

    async def handle_rank_level(self, event: AstrMessageEvent):
        """境界排行"""
        success, msg = await self.rank_mgr.get_level_ranking()
        yield event.plain_result(msg)

    async def handle_rank_power(self, event: AstrMessageEvent):
        """战力排行"""
        success, msg = await self.rank_mgr.get_power_ranking()
        yield event.plain_result(msg)

    async def handle_rank_wealth(self, event: AstrMessageEvent):
        """财富排行"""
        success, msg = await self.rank_mgr.get_wealth_ranking()
        yield event.plain_result(msg)

    async def handle_rank_deposit(self, event: AstrMessageEvent):
        """存款排行"""
        success, msg = await self.rank_mgr.get_deposit_ranking()
        yield event.plain_result(msg)
