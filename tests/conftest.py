"""
Pytest configuration for plugin tests.

The plugin's managers/__init__.py triggers a chain of relative imports
that fail when tests are discovered from the AstrBot project root.
This conftest provides a helper to load modules via importlib.util,
bypassing the package __init__ chain entirely.
"""

import importlib.util
import os
import sys

# Mock astrbot before any plugin module is imported
import unittest.mock as _mock
from pathlib import Path

sys.modules.setdefault("astrbot", _mock.MagicMock())
sys.modules.setdefault("astrbot.api", _mock.MagicMock())
sys.modules.setdefault("astrbot.api.logger", _mock.MagicMock())

# Determine the plugin root directory
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def load_module(mod_name: str, rel_path: str):
    """Load a module from the plugin tree without triggering its package __init__.py.

    Args:
        mod_name: The name to register the module under (e.g. ``"enemy_manager"``).
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
