# core/breakthrough_fortune.py
"""Breakthrough fortune wheel - pure random logic for post-breakthrough drops.

This module keeps the random decision tree free of database side effects so it
can be unit-tested with seeded ``random.Random`` instances.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

# Defaults for the "fortune" section in game_config.json.
# Rates are mutually exclusive and must sum to <= 1.0; the remainder is "nothing".
_FORTUNE_DEFAULTS = {
    "weapon_rate": 0.12,
    "heart_method_rate": 0.08,
    "pill_rate": 0.20,
    "level_window": 10,
    "pill_count_min": 1,
    "pill_count_max": 2,
}


def get_fortune_config(game_config: dict) -> dict:
    """Load fortune config with defaults.

    Args:
        game_config: The full game configuration dict (or a subset containing
            a ``fortune`` key).

    Returns:
        A dict with all required fortune keys populated.
    """
    fortune_cfg = (
        game_config.get("fortune", {}) if isinstance(game_config, dict) else {}
    )
    cfg = {**_FORTUNE_DEFAULTS, **fortune_cfg}

    # Clamp rates to valid ranges.
    for key in ("weapon_rate", "heart_method_rate", "pill_rate"):
        cfg[key] = max(0.0, min(1.0, float(cfg.get(key, 0.0))))
    cfg["level_window"] = max(0, int(cfg.get("level_window", 10)))
    cfg["pill_count_min"] = max(1, int(cfg.get("pill_count_min", 1)))
    cfg["pill_count_max"] = max(
        cfg["pill_count_min"], int(cfg.get("pill_count_max", 1))
    )
    return cfg


def filter_items_by_level(
    items: Iterable[dict],
    new_level_index: int,
    level_window: int = 10,
) -> list[dict]:
    """Filter items eligible for a breakthrough fortune drop.

    Items are eligible when::

        new_level_index - level_window <= required_level_index <= new_level_index

    and they carry a positive ``shop_weight``.

    Args:
        items: Iterable of item definitions.
        new_level_index: The player's level index after a successful breakthrough.
        level_window: How many levels below the new level are still considered
            useful (default 10).

    Returns:
        A list of eligible item definitions with ``shop_weight`` > 0.
    """
    min_level = max(0, new_level_index - level_window)
    eligible = []
    for item in items:
        if not isinstance(item, dict):
            continue
        required = item.get("required_level_index", 0)
        weight = item.get("shop_weight", 0)
        if min_level <= required <= new_level_index and weight > 0:
            eligible.append(item)
    return eligible


def weighted_random_choice(
    items: list[dict],
    rng: random.Random,
    weight_key: str = "shop_weight",
) -> dict | None:
    """Pick one item by weight.

    Args:
        items: List of item definitions.
        rng: Random source (seeded in tests).
        weight_key: The dict key to read the weight from.

    Returns:
        The chosen item, or ``None`` if the pool is empty or has no weight.
    """
    if not items:
        return None

    total_weight = sum(item.get(weight_key, 0) for item in items)
    if total_weight <= 0:
        return None

    roll = rng.random() * total_weight
    cumulative = 0.0
    for item in items:
        cumulative += item.get(weight_key, 0)
        if roll < cumulative:
            return item
    return items[-1]


def _roll_pill_drops(
    pill_pool: list[dict],
    rng: random.Random,
    count_min: int,
    count_max: int,
) -> list[dict]:
    """Roll 1~2 pill drops with replacement and return aggregated counts."""
    count = rng.randint(count_min, count_max) if count_min < count_max else count_min
    raw = [weighted_random_choice(pill_pool, rng) for _ in range(count)]

    counts: dict[str, int] = {}
    data_map: dict[str, dict] = {}
    for item in raw:
        if item is None:
            continue
        name = item.get("name", "")
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        data_map[name] = item

    return [
        {"name": name, "count": cnt, "data": data_map[name]}
        for name, cnt in counts.items()
    ]


def roll_breakthrough_fortune(
    rng: random.Random,
    game_config: dict,
    new_level_index: int,
    weapons: Iterable[dict],
    heart_methods: Iterable[dict],
    pills: Iterable[dict],
) -> dict | None:
    """Roll the post-breakthrough fortune wheel.

    The result is mutually exclusive: exactly one of weapon / heart_method /
    pill / nothing is returned. If the selected category has no eligible items,
    the drop is empty (``None``).

    Args:
        rng: Random source; use a seeded ``random.Random`` in tests.
        game_config: Game configuration dict containing the ``fortune`` section.
        weapons: All weapon definitions.
        heart_methods: All heart-method definitions.
        pills: All pill definitions (usually utility pills + breakthrough pills).

    Returns:
        A result dict describing the drop, or ``None`` for no drop.

        Result shape::

            {
                "type": "weapon" | "heart_method" | "pill",
                "items": [{"name": str, "count": int, "data": dict}, ...],
                "message": str,
            }
    """
    cfg = get_fortune_config(game_config)

    total_rate = cfg["weapon_rate"] + cfg["heart_method_rate"] + cfg["pill_rate"]
    roll = rng.random()
    if roll >= total_rate:
        return None

    level_window = cfg["level_window"]

    if roll < cfg["weapon_rate"]:
        pool = filter_items_by_level(weapons, new_level_index, level_window)
        chosen = weighted_random_choice(pool, rng)
        if chosen is None:
            return None
        name = chosen.get("name", "未知武器")
        rank = chosen.get("rank", "")
        return {
            "type": "weapon",
            "items": [{"name": name, "count": 1, "data": chosen}],
            "message": f"🎁 机缘天降，获得武器【{name}】（{rank}）！",
        }

    if roll < cfg["weapon_rate"] + cfg["heart_method_rate"]:
        pool = filter_items_by_level(heart_methods, new_level_index, level_window)
        chosen = weighted_random_choice(pool, rng)
        if chosen is None:
            return None
        name = chosen.get("name", "未知心法")
        rank = chosen.get("rank", "")
        return {
            "type": "heart_method",
            "items": [{"name": name, "count": 1, "data": chosen}],
            "message": f"🎁 福至心灵，获得心法【{name}】（{rank}）！",
        }

    # Pill drop
    pool = filter_items_by_level(pills, new_level_index, level_window)
    dropped = _roll_pill_drops(pool, rng, cfg["pill_count_min"], cfg["pill_count_max"])
    if not dropped:
        return None
    parts = [f"【{item['name']}】x{item['count']}" for item in dropped]
    return {
        "type": "pill",
        "items": dropped,
        "message": "🎁 仙缘际会，获得丹药" + "、".join(parts) + "！",
    }


def format_fortune_message(result: dict | None) -> str:
    """Format a fortune result for appending to the breakthrough success message.

    Args:
        result: The result dict from ``roll_breakthrough_fortune`` or ``None``.

    Returns:
        A Chinese message, or an empty string when there is no drop.
    """
    if result is None:
        return ""
    return result.get("message", "")
