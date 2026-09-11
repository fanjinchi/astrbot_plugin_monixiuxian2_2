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

Line-break ownership contract (bd -ju1 / -tnr)
----------------------------------------------
**Copy never owns line breaks at its edges; code and panel templates do.** A
narrative pool entry may contain internal newlines (multi-line flavor text is
fine), but it must not start or end with whitespace: whoever concatenates the
result (a panel template's ``\n``, or a call site appending a block) owns the
separator. Two independent enforcements implement this:

1. :func:`select_narrative_pool` strips stray edge whitespace off every entry
   at render time (the safety net -- it also fixes the mixed case where a
   template already supplies the newline), warning once per scene.
2. ``scripts/sync_copy_variants_to_config.py`` warns on the same condition
   while importing ``design_docs`` copy, so the offending draft gets fixed at
   the source instead of relying on the net.

Slots that may legitimately render empty (``{streak_bonus_msg}``) additionally
need their newline *inside* the conditional at the call site -- see
``core/breakthrough_manager.py`` -- otherwise an absent line leaves a blank row.
Panel templates (the dual-slot ``panel`` key) are excluded from stripping: they
*are* the newline owner.
"""

import random
import string
from typing import Any

from astrbot.api import logger

# Scenes whose stray edge whitespace has already been reported this process.
_EDGE_WS_WARNED: set[str] = set()

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


def _sanitize_entry_text(text: str, scene_label: str) -> str:
    """Drop stray edge whitespace from one pool entry (line-break ownership contract).

    Args:
        text: Raw pool entry as configured (may carry leading/trailing blanks).
        scene_label: Human-readable scene key used in the warning, e.g.
            ``breakthrough.pity_hint`` or ``adventure.desc_variants``.

    Returns:
        The entry with leading/trailing whitespace removed; interior newlines are
        untouched because multi-line flavor copy is legitimate.
    """
    cleaned = text.strip()
    if cleaned != text and scene_label not in _EDGE_WS_WARNED:
        # Warn once per scene per process: copy is rendered on hot paths (every
        # combat round), so an unconditional warning would flood the log.
        _EDGE_WS_WARNED.add(scene_label)
        logger.warning(
            f"叙事文案 {scene_label} 自带首尾空白/换行，已在渲染时剔除。"
            "换行归代码或面板模板所有（utils/narrative_text.py 模块文档）；"
            "design_docs 稿子请去掉多余换行后重新导入。"
        )
    return cleaned


def select_narrative_pool(
    value: Any,
    *,
    route: str | None = None,
    level_index: int | None = None,
    scene_label: str = "",
) -> list[str]:
    """Normalize a narrative scene value into a flat list of template strings.

    Supports the three pool scene shapes from the narrative-text-config spec: a
    single template (str), a flat variant pool (list), and a realm-segment
    bucketed pool (dict keyed by ``NARRATIVE_BUCKET_KEYS``). Bucketed pools
    merge the player's current segment bucket with the 通用 bucket; unknown
    bucket keys are ignored. Entries may be plain strings or
    ``{"text": ..., "route": "灵修"|"体修"}`` dicts — route-tagged entries
    only participate for players of that route, and callers that do not know
    the route (``route=None``) exclude tagged entries conservatively.

    The fourth scene shape (dual-slot: bucketed flavor pool + single-source
    ``panel`` template) is handled by :func:`render_narrative`, which strips
    the ``panel`` key before delegating pool selection here — this function
    deliberately stays dual-slot-agnostic so the adventure ``desc_variants``
    reuse path is unaffected.

    This is the single shared implementation used both by narrative scenes and
    by adventure event ``desc_variants`` bucket selection.

    Every entry is normalized by :func:`_sanitize_entry_text` -- stray edge
    whitespace is removed here so no scene can render a blank line (bd -ju1).
    Entries that sanitize to an empty string are dropped, so a whitespace-only
    entry can neither render a blank message nor block the caller's
    empty-pool fallback. Pass ``scene_label`` (``section.scene``) to get a
    one-shot warning naming the offending scene. Panel templates are *not*
    pool entries and stay untouched.
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
            cleaned = _sanitize_entry_text(entry, scene_label)
        else:
            tagged_route = entry.get("route")
            if tagged_route and tagged_route != route:
                continue
            text = entry.get("text")
            if not isinstance(text, str):
                continue
            cleaned = _sanitize_entry_text(text, scene_label)
        # A whitespace-only entry sanitizes to "" -- keeping it would render a
        # blank message and defeat the empty-pool fallback in render_narrative.
        if cleaned:
            pool.append(cleaned)
    return pool


def _is_dual_slot(value: Any) -> bool:
    """Return True when the scene value is the dual-slot shape.

    Dual-slot = dict with a string ``panel`` key (single-source mechanical
    panel) and no ``text`` key (which would make it a single route-tagged
    pool entry). The remaining keys hold the bucketed flavor pool.
    """
    return (
        isinstance(value, dict)
        and isinstance(value.get("panel"), str)
        and not isinstance(value.get("text"), str)
    )


def _render_dual_slot(
    value: dict,
    variables: dict | None,
    *,
    route: str | None,
    level_index: int | None,
    scene_label: str,
) -> str:
    """Render a dual-slot scene: one flavor intro from the bucketed pool, then the panel.

    Pool selection reuses :func:`select_narrative_pool` with the ``panel`` key
    stripped. An empty flavor pool (unconfigured or emptied by route
    filtering) yields panel-only output — this path never falls back to the
    embedded default pool, because the panel is the scene's authoritative
    mechanical carrier and mixing in default flavor copy would duplicate it.
    Render failures degrade without raising: a broken flavor entry is skipped
    (panel only), a broken panel renders as the raw template.
    """
    flavor_source = {k: v for k, v in value.items() if k != "panel"}
    flavor_pool = select_narrative_pool(
        flavor_source, route=route, level_index=level_index, scene_label=scene_label
    )
    flavor = ""
    if flavor_pool:
        candidate = random.choice(flavor_pool)
        try:
            flavor = candidate.format_map(dict(variables or {}))
        except (KeyError, IndexError, ValueError) as exc:
            logger.error(f"叙事 flavor 渲染失败 {scene_label}: {exc}")
    panel_template = value["panel"]
    try:
        panel = panel_template.format_map(dict(variables or {}))
    except (KeyError, IndexError, ValueError) as exc:
        logger.error(f"叙事面板渲染失败 {scene_label}: {exc}")
        panel = panel_template
    return f"{flavor}\n{panel}" if flavor else panel


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

    Scene values support four shapes: single template (str), flat variant pool
    (list), bucketed pool (dict keyed by NARRATIVE_BUCKET_KEYS), and dual-slot
    (dict with a string ``panel`` key). Dual-slot scenes compose one flavor
    intro from the bucketed pool with the single-source panel template
    (``flavor + "\\n" + panel``) — see :func:`_render_dual_slot`. Dual-slot
    call sites should pass ``route``/``level_index`` so the bucketed flavor
    pool and route tags actually take effect.
    """
    value = None
    cfg = getattr(config_manager, "narrative_config", None)
    if isinstance(cfg, dict):
        section_cfg = cfg.get(section)
        if isinstance(section_cfg, dict):
            value = section_cfg.get(scene)

    if _is_dual_slot(value):
        # Dual-slot scenes short-circuit before the default-pool fallback: the
        # panel is authoritative, and an empty flavor pool means panel-only.
        return _render_dual_slot(
            value,
            variables,
            route=route,
            level_index=level_index,
            scene_label=f"{section}.{scene}",
        )

    default_value = DEFAULT_NARRATIVE_CONFIG.get(section, {}).get(scene)
    scene_label = f"{section}.{scene}"
    pool = select_narrative_pool(
        value, route=route, level_index=level_index, scene_label=scene_label
    )
    if not pool:
        # Missing scene or a pool emptied by route filtering: fall back to the
        # embedded default copy (same fallback path as contract violations).
        pool = select_narrative_pool(
            default_value, route=route, level_index=level_index, scene_label=scene_label
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
