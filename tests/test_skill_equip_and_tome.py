"""Tests for the equip-from-learned-skills contract.

Covers the spec delta in
openspec/changes/equip-from-learned-skills/specs/skill-system/spec.md:

- Ring tomes are study-target proof only, never an equip source.
- Equip/activate reads the learned-skill table (player_skills) exclusively.
- Transferring a tome does not affect the source player's learned state.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_core_pkg = load_package_module(
    "core/__init__.py", "astrbot_plugin_monixiuxian2_2.core"
)
_config_mod = load_package_module(
    "config_manager.py", "astrbot_plugin_monixiuxian2_2.config_manager"
)
ConfigManager = _config_mod.ConfigManager
_skill_mod = load_package_module(
    "core/skill_manager.py", "astrbot_plugin_monixiuxian2_2.core.skill_manager"
)
SkillManager = _skill_mod.SkillManager
_ring_mod = load_package_module(
    "core/storage_ring_manager.py",
    "astrbot_plugin_monixiuxian2_2.core.storage_ring_manager",
)
StorageRingManager = _ring_mod.StorageRingManager
_handler_mod = load_package_module(
    "handlers/technique_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.technique_handler",
)
TechniqueHandler = _handler_mod.TechniqueHandler


@pytest.fixture
def config_manager():
    return ConfigManager(PLUGIN_ROOT)


class FakeDbExt:
    """In-memory player_skills store mirroring database_extended CRUD."""

    def __init__(self):
        self.player_skills: dict[tuple[str, str], dict] = {}
        self.get_user_cd = AsyncMock(return_value=None)
        self.get_active_loan = AsyncMock(return_value=None)

    async def is_skill_learned(self, user_id: str, skill_id: str) -> bool:
        return (user_id, skill_id) in self.player_skills

    async def get_star_level(self, user_id: str, skill_id: str) -> int:
        entry = self.player_skills.get((user_id, skill_id))
        return entry["star_level"] if entry else 1

    async def learn_or_star_up(
        self,
        user_id: str,
        skill_id: str,
        source: str = "",
        max_star: int = 3,
        max_star_exp_compensation: int = 0,
    ) -> tuple[bool, int]:
        key = (user_id, skill_id)
        if key not in self.player_skills:
            self.player_skills[key] = {"star_level": 1, "source": source}
            return True, 1
        star = min(self.player_skills[key]["star_level"] + 1, max_star)
        self.player_skills[key]["star_level"] = star
        return False, star


class FakePlayer:
    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "u1")
        self.state = kwargs.get("state", "空闲")
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.main_technique = kwargs.get("main_technique", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.storage_ring_items = kwargs.get("storage_ring_items", "{}")
        self.study_target = kwargs.get("study_target", "")

    def get_techniques_list(self):
        try:
            return json.loads(self.techniques)
        except json.JSONDecodeError:
            return []

    def set_techniques_list(self, techniques_list):
        self.techniques = json.dumps(techniques_list, ensure_ascii=False)

    def get_storage_ring_items(self):
        try:
            return json.loads(self.storage_ring_items)
        except json.JSONDecodeError:
            return {}


def make_handler(cfg, ext):
    db = MagicMock()
    db.ext = ext
    db.update_player = AsyncMock()
    skill_mgr = SkillManager(cfg, db)
    ring_mgr = StorageRingManager(db, cfg)
    return TechniqueHandler(db, cfg, skill_mgr, ring_mgr), db


def make_event(text: str) -> MagicMock:
    event = MagicMock()
    event.get_sender_id.return_value = "u1"
    event.get_message_str.return_value = text
    event.plain_result = MagicMock(return_value="plain")
    return event


# ---------------------------------------------------------------------------
# Config layer: tome items align with skill names
# ---------------------------------------------------------------------------


def test_legacy_tomes_flagged_and_removed_from_shop(config_manager):
    """Old type=功法 items (4001-4010) are legacy and off the shop."""
    items = config_manager.items_data
    assert items["长春功残篇"]["legacy"] is True
    assert items["长春功残篇"]["shop_weight"] == 0
    assert items["焚天诀上卷"]["legacy"] is True


def test_new_tomes_aligned_to_skill_names(config_manager):
    """Name-aligned tomes exist, are type=功法 and sellable."""
    items = config_manager.items_data
    for name in ("基础吐纳", "铁布衫"):
        assert items[name]["type"] == "功法"
        assert items[name]["shop_weight"] > 0
        assert items[name]["price"] > 0


def test_tome_name_maps_to_skill_id(config_manager):
    """Tome name == skill name must resolve to the skill id (ownership proof)."""
    skill_mgr = SkillManager(config_manager)
    assert skill_mgr._find_skill_id_by_name("基础吐纳") == "common_001"
    assert skill_mgr._find_skill_id_by_name("铁布衫") == "common_002"


def test_drop_tables_use_skill_names():
    """Drop tables must no longer reference the disconnected old tome names."""
    stale = ("功法残页", "远古秘籍")
    for rel in ("config/adventure_config.json", "config/enemies.json",
                "config/game_config.json", "config/bounty_templates.json"):
        with (PLUGIN_ROOT / rel).open(encoding="utf-8") as f:
            text = f.read()
        assert not any(name in text for name in stale), f"{rel} still has stale names"
        assert "基础吐纳" in text or "铁布衫" in text, f"{rel} lacks aligned tomes"


# ---------------------------------------------------------------------------
# Ring layer: tomes are storable, pills are not
# ---------------------------------------------------------------------------


def test_tome_can_be_stored_in_ring(config_manager):
    ring_mgr = StorageRingManager(MagicMock(), config_manager)
    ok, _ = ring_mgr.can_store_item("基础吐纳")
    assert ok is True
    assert ring_mgr.is_pill("基础吐纳") is False


# ---------------------------------------------------------------------------
# Ownership chain: ring tome -> study target -> learned -> equip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ring_tome_enables_study_target(config_manager):
    """A name-aligned tome in the ring is ownership proof for study target."""
    handler, _ = make_handler(config_manager, FakeDbExt())
    player = FakePlayer(storage_ring_items='{"基础吐纳": 1}')

    owned = handler._get_owned_skill_ids(player)
    assert "common_001" in owned

    ok, msg = await handler.skill_manager.set_study_target(player, "common_001", owned)
    assert ok is True
    assert player.study_target == "common_001"


@pytest.mark.asyncio
async def test_unlearned_activate_rejected_with_new_hint(config_manager):
    """Activating an unlearned skill is rejected with the corrected hint."""
    handler, _ = make_handler(config_manager, FakeDbExt())
    handler.db.get_player_by_id = AsyncMock(return_value=FakePlayer())

    event = make_event("激活功法 基础吐纳")
    async for _ in handler.handle_activate_technique(event, "基础吐纳"):
        pass

    msg = event.plain_result.call_args[0][0]
    assert "尚未领悟" in msg
    assert "需先拥有该功法秘籍" in msg


@pytest.mark.asyncio
async def test_activate_works_without_ring_tome_after_transfer(config_manager):
    """Equip reads the learned table only: after gifting the tome away, the
    source player (who learned it) can still equip the skill."""
    ext = FakeDbExt()
    ext.player_skills[("u1", "common_001")] = {"star_level": 1, "source": "study"}
    handler, _ = make_handler(config_manager, ext)
    # Ring is empty: the tome was transferred to another player.
    player = FakePlayer(storage_ring_items="{}", techniques="[]")
    handler.db.get_player_by_id = AsyncMock(return_value=player)

    event = make_event("激活功法 基础吐纳")
    async for _ in handler.handle_activate_technique(event, "基础吐纳"):
        pass

    msg = event.plain_result.call_args[0][0]
    assert "已激活功法【基础吐纳】" in msg
    assert player.get_techniques_list() == ["基础吐纳"]


@pytest.mark.asyncio
async def test_unlearned_without_tome_rejected(config_manager):
    """Without a tome and without a learned record, activation is rejected."""
    handler, _ = make_handler(config_manager, FakeDbExt())
    handler.db.get_player_by_id = AsyncMock(return_value=FakePlayer())

    event = make_event("激活功法 铁布衫")
    async for _ in handler.handle_activate_technique(event, "铁布衫"):
        pass

    msg = event.plain_result.call_args[0][0]
    assert "尚未领悟" in msg
