# core/encounter_store.py
"""In-memory pending-encounter store (add-rift-encounters design D1/D8).

After a rift/adventure settlement, an encounter (puzzle/beast/legacy) may be
pended for the player to answer at leisure via ``探索秘境`` subcommands.
Entries live in process memory only - a plugin hot-reload wipes them, which is
acceptable because ignoring or losing an encounter carries zero penalty
(design D1). Expiry is lazy: entries carry ``expires_at`` and are judged on
read, so no background task (or ``UserStatus``/``user_cd`` involvement) is
needed.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Encounter kinds; at most one pending entry per player per kind.
KIND_PUZZLE = "puzzle"
KIND_BEAST = "beast"
KIND_LEGACY = "legacy"
ENCOUNTER_KINDS = (KIND_PUZZLE, KIND_BEAST, KIND_LEGACY)

# Default entry lifetime (design D1: 10 minutes).
DEFAULT_TTL_SECONDS = 600


@dataclass
class PendingEncounter:
    """A single pended encounter entry.

    Attributes:
        user_id: Owning player.
        kind: One of ``ENCOUNTER_KINDS``.
        payload: Kind-specific context (puzzle instance, rift_level,
            enemy_group, legacy_type, source, ...). Kept by reference so the
            encounter layer can mutate state in place (e.g. puzzle attempts).
        created_at: Epoch seconds when pended.
        expires_at: Epoch seconds at/after which the encounter is gone.
    """

    user_id: str
    kind: str
    payload: dict[str, Any]
    created_at: float
    expires_at: float

    def is_expired(self, now: float) -> bool:
        """Return whether the entry has reached its TTL at ``now``."""
        return now >= self.expires_at


class EncounterStore:
    """Process-local pending table keyed by (player, kind).

    Same-kind ``pend`` overwrites and refreshes the previous entry (design
    D1); reads lazily drop expired entries. Not thread-safe by design - the
    plugin runs single-process asyncio.
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        time_fn: Callable[[], float] = time.time,
    ):
        """
        Args:
            ttl_seconds: Default entry lifetime when ``pend`` gets no ``ttl``.
            time_fn: Clock source, injectable for deterministic tests.
        """
        self.ttl_seconds = int(ttl_seconds)
        self._time_fn = time_fn
        self._table: dict[str, dict[str, PendingEncounter]] = {}

    def pend(
        self,
        user_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        ttl: int | None = None,
    ) -> PendingEncounter:
        """Pend (or overwrite-refresh) an encounter for a player.

        Args:
            user_id: Owning player.
            kind: Encounter kind; must be one of ``ENCOUNTER_KINDS``.
            payload: Context carried by the entry (kept by reference).
            ttl: Lifetime in seconds; defaults to the store's ``ttl_seconds``.

        Returns:
            The stored entry.

        Raises:
            ValueError: On an unknown encounter kind.
        """
        if kind not in ENCOUNTER_KINDS:
            raise ValueError(f"unknown encounter kind: {kind}")
        now = self._time_fn()
        lifetime = self.ttl_seconds if ttl is None else int(ttl)
        entry = PendingEncounter(
            user_id=user_id,
            kind=kind,
            payload=payload if payload is not None else {},
            created_at=now,
            expires_at=now + lifetime,
        )
        self._table.setdefault(user_id, {})[kind] = entry
        return entry

    def get_active(self, user_id: str, kind: str) -> PendingEncounter | None:
        """Return the player's live entry of ``kind``, dropping it if expired."""
        entry = self._table.get(user_id, {}).get(kind)
        if entry is None:
            return None
        if entry.is_expired(self._time_fn()):
            # 惰性过期：读取时判死并清除（design D1，无需定时任务）
            del self._table[user_id][kind]
            return None
        return entry

    def consume(self, user_id: str, kind: str) -> PendingEncounter | None:
        """Remove and return the player's live entry (None if absent/expired)."""
        entry = self.get_active(user_id, kind)
        if entry is None:
            return None
        del self._table[user_id][kind]
        return entry
