"""Narrative contract helpers: single source for template parsing, pool
iteration, and scene validation.

This module is the single authority (契约深模块) for three concerns that
used to live scattered across ``utils/narrative_text.py`` and
``scripts/sync_copy_variants_to_config.py``:

1. Template variable extraction (:func:`used_vars`) -- string.Formatter
   based, mirror of the former ``narrative_text.extract_template_vars``.
2. Scene value flattening (:func:`iter_scene_entries`), including the
   bucketed-pool flattening (:func:`_iter_pool_entries`) shared by both pool
   selection (narrative_text) and validation/import (config_manager, sync
   script), so the flatten layer stays single-sourced.
3. Per-scene contract validation (:func:`validate_scene`), absorbing the
   checks formerly in ``ConfigManager._check_narrative_scene``; every
   diagnostic carries the exact log text (including the ``[{source}]``
   prefix) that the old code path emitted.

The module is deliberately top-level dependency free: it imports nothing from
astrbot and nothing relative, so it loads identically inside the plugin
package and standalone by file path. Loading it both ways in one process
produces two module objects; this is safe because the module carries no
mutable process state -- constants are immutable tuples and all functions are
pure. Consumers that need both loading routes use the try/except fallback
pattern from ``utils/narrative_text.py``.
"""

import string
from typing import Any

# Valid values for the optional per-entry route tag.
NARRATIVE_ROUTES = ("灵修", "体修")

# Bucket keys for realm-segment copy pools, shared by narrative scenes and
# adventure event desc_variants. 通用 always participates in the merged pool;
# the other four keys map to the season-1 幕表 level segments.
NARRATIVE_BUCKET_KEYS = ("通用", "练气", "筑基", "金丹", "元婴")

_TEMPLATE_FORMATTER = string.Formatter()


def used_vars(template: str) -> set[str]:
    """Extract the ``{var}`` placeholder names referenced by a template.

    Only the root of each field is returned (``{player.name}`` -> ``player``).
    Raises ``ValueError`` on malformed brace usage so callers can report a
    contract violation instead of rendering garbage.

    Args:
        template: A narrative template string.

    Returns:
        The set of root variable names used by the template.

    Raises:
        ValueError: When the template has unbalanced or otherwise malformed
            braces (mirrors the render-time ``str.format_map`` failure mode).
    """
    variables: set[str] = set()
    for _, field_name, _, _ in _TEMPLATE_FORMATTER.parse(template):
        if field_name:
            root = field_name.split(".")[0].split("[")[0]
            if root:
                variables.add(root)
    return variables


def _iter_pool_entries(value: Any) -> list:
    """Flatten a non-bucket scene value into raw pool entries (str or dict).

    Args:
        value: A single template (str), a single route-tagged entry (dict
            with a string ``text`` key), or a flat list. Bucketed pool dicts
            are *not* flattened here -- :func:`iter_scene_entries` walks them
            key by key and flattens each bucket value.

    Returns:
        The raw entries; non-entry items (e.g. numbers, dicts without a
        string ``text`` key) are skipped.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return [value]
    if isinstance(value, list):
        return [e for e in value if isinstance(e, (str, dict))]
    return []


def iter_scene_entries(value: Any):
    """Yield ``(location, entry)`` for every pool entry in a scene value.

    ``location`` is a human-readable marker (bucket/index) used in validation
    error messages. Entries are raw (str or ``{"text", "route"}`` dicts).

    Args:
        value: Any scene shape (single str, flat pool list, bucketed pool
            dict, or dual-slot dict with a string ``panel`` key).

    Yields:
        ``(location, entry)`` pairs; location is ``#<index>`` for flat
        shapes and ``[<bucket>]#<index>`` for bucketed pools (the dual-slot
        ``panel`` key yields ``[panel]#0``).
    """
    if isinstance(value, dict) and not isinstance(value.get("text"), str):
        for bucket, bucket_value in value.items():
            for index, entry in enumerate(_iter_pool_entries(bucket_value)):
                yield f"[{bucket}]#{index}", entry
    else:
        for index, entry in enumerate(_iter_pool_entries(value)):
            yield f"#{index}", entry


def validate_scene(
    section: str,
    scene: str,
    value: Any,
    declared: set[str],
    *,
    source: str,
) -> tuple[bool, list[tuple[str, str]]]:
    """Check one scene value against its declared variable contract.

    Returns ``(usable, diagnostics)``:

    - ``usable`` is False when the scene must be rejected wholesale (malformed
      dual-slot shape, or any entry-level error) so the caller falls back to
      the embedded default;
    - ``diagnostics`` lists ``(severity, message)`` pairs in deterministic
      order, ``severity`` ∈ {"warning", "error"}. Each message already carries
      the ``[{source}]`` prefix and matches the log lines the former
      ``ConfigManager._check_narrative_scene`` emitted *verbatim* -- severity
      is pinned per branch: unknown bucket keys / unknown route tags /
      malformed dual-slot shape are warnings (the dual-slot case warns but
      *rejects* the scene: warning severity and reject decision are
      decoupled); missing ``text`` / unpaired braces / unknown variables are
      errors. The ``叙事配置`` vs ``叙事文案契约违例`` prefixes are assigned
      per branch, not per severity (missing ``text`` is an error logged with
      the former prefix).

    Diagnostics order (matches the former implementation): dual-slot shape
    check → bucket-key loop → per-entry loop (route tag → missing text →
    unpaired braces → unknown variables).

    Dual-slot shape (dict with a string ``panel`` key, no ``text`` key): the
    panel string is validated as a ``[panel]#0`` entry by the shared entry
    loop, and the ``panel`` key is exempt from bucket-key warnings. A
    non-string ``panel`` value, or a dict carrying both ``text`` and
    ``panel``, is a malformed half-shape -- warn and reject the whole scene
    so the caller falls back to the embedded default.

    Args:
        section: Config section name (e.g. ``breakthrough``).
        scene: Scene key inside the section.
        value: The scene value (any of the four scene shapes).
        declared: The variable set the render point declares for this scene.
        source: Label embedded in every diagnostic (e.g. ``配置`` or
            ``内嵌默认``).

    Returns:
        ``(usable, diagnostics)`` as described above.
    """
    diagnostics: list[tuple[str, str]] = []
    if isinstance(value, dict) and "panel" in value:
        # Short-circuit before entry iteration: a non-string panel would
        # otherwise be validated as a flavor-bucket entry and mask the real
        # "malformed dual-slot shape" diagnosis.
        if not isinstance(value.get("panel"), str) or isinstance(
            value.get("text"), str
        ):
            diagnostics.append(
                (
                    "warning",
                    f"叙事配置[{source}] {section}.{scene} 双槽形态非法："
                    "panel 键必须为字符串模板，且场景值不得同含 text 键；"
                    "整场景回退内嵌默认。",
                )
            )
            return False, diagnostics
    usable = True
    if isinstance(value, dict) and not isinstance(value.get("text"), str):
        for bucket in value:
            # The dual-slot ``panel`` key is a mechanical panel template, not
            # a bucket key -- exempt from bucket-key warnings (its string
            # value is still validated as a [panel]#0 entry below).
            if bucket == "panel":
                continue
            if bucket not in NARRATIVE_BUCKET_KEYS:
                diagnostics.append(
                    (
                        "warning",
                        f"叙事配置[{source}] {section}.{scene} 存在未知分桶键 "
                        f"{bucket!r}，该桶不会被取用（合法桶键: {NARRATIVE_BUCKET_KEYS}）。",
                    )
                )

    for location, entry in iter_scene_entries(value):
        if isinstance(entry, dict):
            tagged_route = entry.get("route")
            if tagged_route and tagged_route not in NARRATIVE_ROUTES:
                diagnostics.append(
                    (
                        "warning",
                        f"叙事配置[{source}] {section}.{scene}{location} 存在未知路线标注 "
                        f"{tagged_route!r}（合法值: {NARRATIVE_ROUTES}）。",
                    )
                )
            template = entry.get("text")
            if not isinstance(template, str):
                diagnostics.append(
                    (
                        "error",
                        f"叙事配置[{source}] {section}.{scene}{location} 条目缺少 text 字段。",
                    )
                )
                usable = False
                continue
        else:
            template = entry
        try:
            used = used_vars(template)
        except ValueError as exc:
            diagnostics.append(
                (
                    "error",
                    f"叙事文案契约违例[{source}] {section}.{scene}{location}: "
                    f"模板花括号不配对（{exc}）。",
                )
            )
            usable = False
            continue
        unknown = used - declared
        if unknown:
            diagnostics.append(
                (
                    "error",
                    f"叙事文案契约违例[{source}] {section}.{scene}{location}: "
                    f"未知变量 {sorted(unknown)}，该场景已声明变量 {sorted(declared)}。",
                )
            )
            usable = False
    return usable, diagnostics
