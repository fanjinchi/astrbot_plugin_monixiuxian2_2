"""Test helpers: module loader that bypasses the plugin's __init__.py chain.

The plugin's managers/__init__.py triggers relative imports that fail when
pytest discovers tests from the AstrBot project root. This loader uses
importlib.util so each module is loaded without its package __init__.
"""

import importlib
import importlib.util
import os
import sys
import types
from pathlib import Path

# Determine the plugin root directory (two levels up from this file)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# PLUGIN_ROOT lets tests load modules by file path; its parent (data/plugins/)
# makes the plugin importable as a namespace package so _ensure_package can
# prefer the real package over a synthetic stub.
for _p in (PLUGIN_ROOT, PLUGIN_ROOT.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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


def _ensure_package(full_name: str, package_path: Path) -> None:
    """Ensure ``full_name`` is importable in ``sys.modules``.

    Prefers importing the real package: its ``__init__.py`` re-exports names
    that other plugin modules rely on (e.g. ``from ..data import DataBase``).
    Falls back to an empty synthetic package when the real ``__init__.py``
    cannot be imported in the test environment (e.g. ``managers/__init__.py``
    chains into imports that only resolve inside AstrBot). A bare synthetic
    package would shadow the real one and break such imports with
    "cannot import name ... (unknown location)" during collection whenever
    load order put the synthetic stub first.

    Args:
        full_name: Dotted package name (e.g. ``"astrbot_plugin_monixiuxian2_2.data"``).
        package_path: Filesystem path used as ``__path__`` for the synthetic fallback.
    """
    if full_name in sys.modules:
        return
    try:
        importlib.import_module(full_name)
        return
    except Exception:
        pass  # Real __init__ not importable here; use the synthetic stub.
    pkg = types.ModuleType(full_name)
    pkg.__path__ = [os.fspath(package_path)]
    sys.modules[full_name] = pkg


def load_package_module(rel_path: str, full_name: str):
    """Load a module under a synthetic package tree so relative imports resolve.

    This is needed for modules such as ``data/data_manager.py`` that import
    sibling/parent modules with relative imports (e.g. ``from ..models import Player``).

    Args:
        rel_path: Path relative to the plugin root (e.g. ``"data/data_manager.py"``).
        full_name: Dotted module name (e.g. ``"astrbot_plugin_monixiuxian2_2.data.data_manager"``).

    Returns:
        The loaded module object.
    """
    parts = full_name.split(".")
    _ensure_package(parts[0], PLUGIN_ROOT)
    for i in range(2, len(parts)):
        package_name = ".".join(parts[:i])
        package_path = PLUGIN_ROOT / Path(*parts[1:i])
        _ensure_package(package_name, package_path)

    file_path = PLUGIN_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    if spec is None:
        raise ImportError(f"Cannot find spec for {full_name} at {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod
