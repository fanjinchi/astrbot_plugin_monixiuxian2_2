"""Handlers for the fixed world-boss gameplay (E2 cutover).

The three player/admin commands delegate to the D domain service:

- ``世界Boss`` reads :meth:`WorldBossService.get_active` (expiry settles, no
  spawn);
- ``挑战Boss`` runs one atomic :meth:`WorldBossService.challenge` with a
  per-command idempotency key and renders the domain message; busy-state and
  attempt rules stay inside the service;
- ``生成Boss`` / ``GM 生成Boss`` share :func:`spawn_with_message`.

No handler reads ``narrative_config.json`` or constructs its own broadcast.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.world_boss_service import (
    ChallengeResult,
    WorldBossService,
    spawn_with_message,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _format_expiry(epoch: int) -> str:
    """Render an instance expiry epoch in Beijing wall-clock time.

    Args:
        epoch: Unix seconds.

    Returns:
        ``YYYY-MM-DD HH:MM`` string, or ``--`` when the value is unusable.
    """
    if epoch <= 0:
        return "--"
    try:
        return datetime.fromtimestamp(epoch, _SHANGHAI).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "--"


class WorldBossHandlers:
    """Command handlers for the world-boss domain."""

    def __init__(self, db: DataBase, service: WorldBossService):
        self.db = db
        self.service = service

    async def handle_boss_info(self, event: AstrMessageEvent):
        """Render the current active world boss (``世界Boss`` command)."""
        instance = await self.service.get_active()
        if instance is None:
            yield event.plain_result("👹 当前没有活跃的世界 Boss。")
            return
        yield event.plain_result(self._format_instance(instance))

    @staticmethod
    def _format_instance(instance: dict) -> str:
        """Compose the status text of one active instance.

        Args:
            instance: ``world_boss_instances`` row.

        Returns:
            User-facing Chinese status block (no reward promises).
        """
        name = str(instance.get("boss_name") or "未知")
        hp = int(instance.get("current_hp") or 0)
        max_hp = int(instance.get("max_hp") or 0)
        phase = int(instance.get("phase") or 1)
        level = int(instance.get("boss_level") or 0)
        expires_at = int(instance.get("expires_at") or 0)
        return (
            f"👹 当前世界 Boss：{name}\n"
            f"境界等级：{level}\n"
            f"气血：{hp}/{max_hp}\n"
            f"阶段：第 {phase} 阶段\n"
            f"消散时刻：{_format_expiry(expires_at)}\n"
            "发送「挑战Boss」参与讨伐。"
        )

    async def handle_boss_fight(
        self, user_id: str, *, challenge_id: str | None = None
    ) -> tuple[bool, str]:
        """Challenge the active world boss for one player command.

        Args:
            user_id: Challenger user id.
            challenge_id: Optional fixed idempotency key (tests pin it); when
                omitted a unique key is generated for this command.

        Returns:
            (ok, domain message).
        """
        player = await self.db.get_player_by_id(user_id)
        if player is None:
            return False, "❌ 玩家不存在。"
        key = challenge_id or f"wb_cmd:{user_id}:{time.time_ns()}"
        result: ChallengeResult = await self.service.challenge(
            player=player, challenge_id=key
        )
        return bool(result.ok), result.message

    async def handle_spawn_boss(
        self, profile_id: str | None = None
    ) -> tuple[bool, str]:
        """Ensure a world boss exists (management entry, shared three branches).

        Args:
            profile_id: Optional forced profile id (admin entries only).

        Returns:
            (success, user-facing message).
        """
        return await spawn_with_message(self.service, profile_id)
