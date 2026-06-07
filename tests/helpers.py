"""
Test helpers: module loader that bypasses the plugin's __init__.py chain.

The plugin's managers/__init__.py triggers relative imports that fail when
pytest discovers tests from the AstrBot project root. This loader uses
importlib.util so each module is loaded without its package __init__.
"""

import importlib.util
import os
import sys
from pathlib import Path

# Determine the plugin root directory (two levels up from this file)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def load_module(mod_name: str, rel_path: str):
    """Load a module from the plugin tree without triggering its package __init__.py.

    Args:
        mod_name: Name to register the module under (e.g. ``"enemy_manager"``).
        rel_path: Path relative to the plugin root (e.g. ``"managers/enemy_manager.py"``).

    Returns:
        The loaded module object.
    """
    path = os.fspath(PLUGIN_ROOT / rel_path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None:
        raise ImportError(f"Cannot find spec for {mod_name} at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod
