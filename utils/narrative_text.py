# utils/narrative_text.py
"""Narrative template helpers: pool normalization, bucket selection, rendering.

This module is deliberately importable in two ways: as part of the plugin
package and standalone by file path. Managers whose test suites bypass the
package ``__init__`` chain (the try/except ``_load_module`` shim in
``managers/``) can therefore use it from either branch. The embedded default
copy comes from ``data/narrative_defaults/`` — assembled via package import
when available, or by file path when standalone. Both paths read the same
fragment files, so the content is always identical.

Call sites render copy through :func:`render_narrative`; adventure event
``desc_variants`` bucket selection reuses :func:`select_narrative_pool` and
:func:`level_to_narrative_bucket` so bucket semantics stay single-sourced.
"""

import random
import string
from typing import Any

from astrbot.api import logger

try:
    from ..data.narrative_defaults import (
        DEFAULT_NARRATIVE_CONFIG,
        NARRATIVE_SCENE_VARS,
    )
except ImportError:
    # Standalone loading under tests: assemble the defaults package by path.
    import importlib.util
    import sys
    from pathlib import Path

    _init_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "narrative_defaults"
        / "__init__.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "narrative_defaults_standalone", _init_path
    )
    _nd = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _nd
    _spec.loader.exec_module(_nd)
    DEFAULT_NARRATIVE_CONFIG = _nd.DEFAULT_NARRATIVE_CONFIG
    NARRATIVE_SCENE_VARS = _nd.NARRATIVE_SCENE_VARS

# Bucket keys for realm-segment copy pools, shared by narrative scenes and
# adventure event desc_variants. 通用 always participates in the merged pool;
# the other four keys map to the season-1 幕表 level segments.
NARRATIVE_BUCKET_KEYS = ("通用", "练气", "筑基", "金丹", "元婴")

# 1-based level ranges per bucket (season-1 幕表: Lv1-9/10-19/20-29/30-39).
_NARRATIVE_BUCKET_RANGES = (
    (1, 9, "练气"),
    (10, 19, "筑基"),
    (20, 29, "金丹"),
    (30, 39, "元婴"),
)

# Valid values for the optional per-entry route tag.
_NARRATIVE_ROUTES = ("灵修", "体修")

_TEMPLATE_FORMATTER = string.Formatter()


def level_to_narrative_bucket(level_index: int | None) -> str | None:
    """Map a 1-based level index to its narrative copy bucket.

    Args:
        level_index: 1-based player level, or None when unknown.

    Returns:
        The bucket key for the level's realm segment, or None when the level
        is outside the season-1 segments (e.g. Lv40+) — callers treat that as
        "通用 bucket only".
    """
    if level_index is None:
        return None
    for low, high, key in _NARRATIVE_BUCKET_RANGES:
        if low <= level_index <= high:
            return key
    return None


def extract_template_vars(template: str) -> set[str]:
    """Extract the ``{var}`` placeholder names referenced by a template.

    Only the root of each field is returned (``{player.name}`` -> ``player``).
    Raises ``ValueError`` on malformed brace usage so callers can report a
    contract violation instead of rendering garbage.
    """
    variables: set[str] = set()
    for _, field_name, _, _ in _TEMPLATE_FORMATTER.parse(template):
        if field_name:
            root = field_name.split(".")[0].split("[")[0]
            if root:
                variables.add(root)
    return variables


def _iter_pool_entries(value: Any) -> list:
    """Flatten a non-bucket scene value into raw pool entries (str or dict)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return [value]
    if isinstance(value, list):
        return [e for e in value if isinstance(e, (str, dict))]
    return []


def select_narrative_pool(
    value: Any, *, route: str | None = None, level_index: int | None = None
) -> list[str]:
    """Normalize a narrative scene value into a flat list of template strings.

    Supports the three scene shapes from the narrative-text-config spec: a
    single template (str), a flat variant pool (list), and a realm-segment
    bucketed pool (dict keyed by ``NARRATIVE_BUCKET_KEYS``). Bucketed pools
    merge the player's current segment bucket with the 通用 bucket; unknown
    bucket keys are ignored. Entries may be plain strings or
    ``{"text": ..., "route": "灵修"|"体修"}`` dicts — route-tagged entries
    only participate for players of that route, and callers that do not know
    the route (``route=None``) exclude tagged entries conservatively.

    This is the single shared implementation used both by narrative scenes and
    by adventure event ``desc_variants`` bucket selection.
    """
    if isinstance(value, dict) and not isinstance(value.get("text"), str):
        # Bucketed pool: merge current segment bucket with the 通用 bucket.
        entries = _iter_pool_entries(value.get("通用"))
        bucket = level_to_narrative_bucket(level_index)
        if bucket and bucket != "通用":
            entries += _iter_pool_entries(value.get(bucket))
    else:
        entries = _iter_pool_entries(value)

    pool: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            pool.append(entry)
            continue
        tagged_route = entry.get("route")
        if tagged_route and tagged_route != route:
            continue
        text = entry.get("text")
        if isinstance(text, str):
            pool.append(text)
    return pool


def render_narrative(
    config_manager: Any,
    section: str,
    scene: str,
    variables: dict | None = None,
    *,
    route: str | None = None,
    level_index: int | None = None,
) -> str:
    """Pick one template for a narrative scene and render it with variables.

    Resolution order: the manager's loaded ``narrative_config`` first, then the
    embedded defaults from ``data/narrative_defaults/``. Managers without a
    ``narrative_config`` attribute (test fakes) silently use the embedded
    defaults. Never raises: a missing scene, empty pool, or broken template is
    logged and falls back; "" is returned only when no default exists either.
    """
    value = None
    cfg = getattr(config_manager, "narrative_config", None)
    if isinstance(cfg, dict):
        section_cfg = cfg.get(section)
        if isinstance(section_cfg, dict):
            value = section_cfg.get(scene)

    default_value = DEFAULT_NARRATIVE_CONFIG.get(section, {}).get(scene)
    pool = select_narrative_pool(value, route=route, level_index=level_index)
    if not pool:
        # Missing scene or a pool emptied by route filtering: fall back to the
        # embedded default copy (same fallback path as contract violations).
        pool = select_narrative_pool(
            default_value, route=route, level_index=level_index
        )
    if not pool:
        logger.error(f"叙事文案场景未配置且无可用默认: {section}.{scene}")
        return ""

    template = random.choice(pool)
    try:
        return template.format_map(dict(variables or {}))
    except (KeyError, IndexError, ValueError) as exc:
        # Should be impossible after load-time contract validation; degrade to
        # the raw template rather than crashing the command pipeline.
        logger.error(f"叙事模板渲染失败 {section}.{scene}: {exc}")
        return template


def _iter_scene_entries(value: Any):
    """Yield ``(location, entry)`` for every pool entry in a scene value.

    ``location`` is a human-readable marker (bucket/index) used in validation
    error messages. Entries are raw (str or ``{"text", "route"}`` dicts).
    """
    if isinstance(value, dict) and not isinstance(value.get("text"), str):
        for bucket, bucket_value in value.items():
            for index, entry in enumerate(_iter_pool_entries(bucket_value)):
                yield f"[{bucket}]#{index}", entry
    else:
        for index, entry in enumerate(_iter_pool_entries(value)):
            yield f"#{index}", entry
