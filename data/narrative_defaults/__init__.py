# data/narrative_defaults/__init__.py
"""Assemble the embedded default narrative config from per-domain fragments.

The default copy for each narrative domain lives in its own module so domains
can be worked on independently without edit conflicts. ``default_configs.py``
re-exports the assembled constants, and ``ConfigManager`` materializes them to
``config/narrative_config.json`` on first load.

Fragment contract: each domain module exposes

- ``SCENES``: ``{scene_key: template | pool | bucketed_pool}`` — the embedded
  default copy, copied verbatim from the original hard-coded strings.
- ``SCENE_VARS``: ``{scene_key: {variable, ...}}`` — the interpolation
  variables each scene's render point provides, used by load-time contract
  validation (``ConfigManager._validate_narrative_config``).

Scene values support three shapes (see ``utils/narrative_text.py``):
a single template (str), a flat variant pool (list), and a realm-segment
bucketed pool (dict keyed by 通用/练气/筑基/金丹/元婴). Pool entries may be
plain strings or ``{"text": ..., "route": "灵修"|"体修"}`` dicts.

The ImportError fallback lets ``utils/narrative_text.py`` load this package by
file path when managers are loaded standalone under tests (their try/except
shim bypasses the package tree).
"""

try:
    from . import breakthrough, combat, cultivation, fortune, legacy_encounter
except ImportError:
    import importlib.util
    import sys
    from pathlib import Path

    def _load_fragment(name: str):
        """Load a sibling fragment module by file path (standalone fallback)."""
        spec = importlib.util.spec_from_file_location(
            f"narrative_defaults_{name}", Path(__file__).with_name(f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    breakthrough = _load_fragment("breakthrough")
    combat = _load_fragment("combat")
    cultivation = _load_fragment("cultivation")
    fortune = _load_fragment("fortune")
    legacy_encounter = _load_fragment("legacy_encounter")

_DOMAIN_MODULES = {
    "breakthrough": breakthrough,
    "combat": combat,
    "cultivation": cultivation,
    "fortune": fortune,
    "legacy_encounter": legacy_encounter,
}

DEFAULT_NARRATIVE_CONFIG: dict = {
    section: module.SCENES for section, module in _DOMAIN_MODULES.items()
}

NARRATIVE_SCENE_VARS: dict[str, dict[str, set[str]]] = {
    section: module.SCENE_VARS for section, module in _DOMAIN_MODULES.items()
}
