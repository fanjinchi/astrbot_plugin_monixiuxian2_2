"""Guard tests for the game_config defaults.

``config/game_config.json`` is the shipped runtime file; ``GAME_CONFIG`` in
``data/default_configs.py`` is what ``ConfigManager`` materializes when that file
is missing. The two must stay in sync, otherwise a fresh deployment would start
from a different parameter set than an upgraded one.
"""

import json
import shutil
from pathlib import Path

from tests.helpers import load_package_module

_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager

_defaults_mod = load_package_module(
    "data/default_configs.py", "astrbot_plugin_monixiuxian2_2.data.default_configs"
)
GAME_CONFIG = _defaults_mod.GAME_CONFIG

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_default_matches_shipped_file():
    """GAME_CONFIG must be identical to the shipped config/game_config.json.

    Compared through ``json.dumps`` instead of ``==`` on purpose: ``True == 1``
    and ``3 == 3.0`` in Python, so a plain dict comparison would silently accept
    a bool/int or int/float type drift that changes how the value is consumed.
    """
    shipped = json.loads(
        (PLUGIN_ROOT / "config" / "game_config.json").read_text(encoding="utf-8")
    )
    assert json.dumps(GAME_CONFIG, ensure_ascii=False, sort_keys=True) == json.dumps(
        shipped, ensure_ascii=False, sort_keys=True
    )


def test_missing_file_materializes_full_default(tmp_path):
    """A missing game_config.json must be materialized from GAME_CONFIG, not {}."""
    plugin_root = tmp_path / "plugin"
    shutil.copytree(PLUGIN_ROOT / "config", plugin_root / "config")
    (plugin_root / "config" / "game_config.json").unlink()

    config_manager = ConfigManager(plugin_root)

    created = plugin_root / "config" / "game_config.json"
    assert created.exists()
    assert json.loads(created.read_text(encoding="utf-8")) == GAME_CONFIG
    assert config_manager.game_config == GAME_CONFIG
