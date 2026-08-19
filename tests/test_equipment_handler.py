"""Regression tests for handlers/equipment_handler.py.

Uses load_package_module to keep relative imports working.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_package_module

# Ensure the plugin package tree and core sub-package are present before
# importing the handler (which uses relative imports).
_core_pkg = load_package_module(
    "core/__init__.py", "astrbot_plugin_monixiuxian2_2.core"
)
_handler_mod = load_package_module(
    "handlers/equipment_handler.py",
    "astrbot_plugin_monixiuxian2_2.handlers.equipment_handler",
)
EquipmentHandler = _handler_mod.EquipmentHandler


class FakeSkillManager:
    """Minimal SkillManager stub for equipment handler tests."""

    def __init__(self):
        self.skills_data = {
            "基础吐纳": {"id": "common_001"},
            "铁布衫": {"id": "common_002"},
            "御剑术": {"id": "spirit_001"},
            "烈火诀": {"id": "fire_001"},
        }
        self.learned_skills = set()  # skill_id set
        self._skill_cfg = {"max_technique_slots": 4}

    def _find_skill_id_by_name(self, name: str) -> str | None:
        skill = self.skills_data.get(name)
        if isinstance(skill, dict):
            return skill.get("id")
        return None

    async def _is_skill_learned(self, player, skill_id: str) -> bool:
        return skill_id in self.learned_skills

    async def can_equip_technique(self, player, technique_name, all_skill_ids):
        skill_id = self._find_skill_id_by_name(technique_name)
        if skill_id is None:
            return False, f"未找到功法【{technique_name}】"
        if skill_id not in set(all_skill_ids):
            return False, f"功法【{technique_name}】尚未领悟，无法装备"
        if not await self._is_skill_learned(player, skill_id):
            return False, f"功法【{technique_name}】尚未领悟，无法装备"
        return True, ""

    async def set_study_target(self, player, skill_id, owned_skill_ids):
        if skill_id not in owned_skill_ids:
            return False, "你尚未拥有该功法，无法设为修习目标"
        if skill_id in self.learned_skills:
            return False, "该功法已领悟，无需再修习"
        player.study_target = skill_id
        return True, "已将【基础吐纳】设为修习目标"


class FakePlayer:
    """Minimal Player stub for equipment handler tests."""

    def __init__(self, **kwargs):
        self.user_id = kwargs.get("user_id", "u1")
        self.user_name = kwargs.get("user_name", "Tester")
        self.state = kwargs.get("state", "空闲")
        self.level_index = kwargs.get("level_index", 1)
        self.weapon = kwargs.get("weapon", "")
        self.armor = kwargs.get("armor", "")
        self.main_technique = kwargs.get("main_technique", "")
        self.techniques = kwargs.get("techniques", "[]")
        self.storage_ring_items = kwargs.get("storage_ring_items", "{}")
        self.study_target = kwargs.get("study_target", "")

    def get_techniques_list(self):
        try:
            return json.loads(self.techniques)
        except Exception:
            return []

    def set_techniques_list(self, techniques_list):
        self.techniques = json.dumps(techniques_list, ensure_ascii=False)

    def get_storage_ring_items(self):
        try:
            return json.loads(self.storage_ring_items)
        except Exception:
            return {}


class FakeConfigManager:
    def __init__(self):
        self.items_data = {
            "基础吐纳": {"type": "功法", "rank": "凡品"},
            "铁布衫": {"type": "功法", "rank": "凡品"},
            "御剑术": {"type": "功法", "rank": "灵品"},
            "烈火诀": {"type": "功法", "rank": "灵品"},
        }
        self.weapons_data = {}


@pytest.fixture
def handler():
    db = MagicMock()
    db.update_player = AsyncMock()
    ext = MagicMock()
    ext.get_user_cd = AsyncMock(return_value=None)
    db.ext = ext
    db.get_player_by_id = AsyncMock()
    cfg = FakeConfigManager()
    skill_mgr = FakeSkillManager()
    return EquipmentHandler(db, cfg, skill_mgr)


class TestCollectOwnedSkillIds:
    def test_collects_from_all_sources(self, handler):
        """Owned skill IDs include storage, equipped techniques and current item."""
        player = FakePlayer(
            techniques='["基础吐纳"]',
            storage_ring_items='{"御剑术": 1}',
        )
        ids = handler._collect_owned_skill_ids(player, "基础吐纳")
        assert "common_001" in ids
        assert "spirit_001" in ids  # from storage ring


class TestEquipTechniqueValidation:
    @pytest.mark.asyncio
    async def test_unlearned_technique_is_rejected(self, handler):
        """Unlearned technique redirects to study target (now set as study target)."""
        player = FakePlayer(
            user_id="u1",
            techniques="[]",
            storage_ring_items='{"基础吐纳": 1}',
        )
        handler.skill_manager.learned_skills = set()
        handler.db.get_player_by_id = AsyncMock(return_value=player)
        handler.storage_ring_manager.has_item = MagicMock(return_value=True)

        event = MagicMock()
        event.get_sender_id.return_value = "u1"
        event.get_message_str.return_value = "装备 基础吐纳"
        event.plain_result = MagicMock(return_value="plain")
        async for _ in handler.handle_equip_item(event, "基础吐纳"):
            pass

        msg = event.plain_result.call_args[0][0]
        # Should succeed as study target is set
        assert "已将" in msg or "设为修习目标" in msg

    @pytest.mark.asyncio
    async def test_slot_limit_unlearned_is_study_target(self, handler):
        """Unlearned technique is now set as study target, not rejected."""
        player = FakePlayer(
            user_id="u1",
            techniques='["基础吐纳","铁布衫","御剑术"]',
            storage_ring_items='{"烈火诀": 1}',
        )
        handler.skill_manager.learned_skills = set()
        handler.db.get_player_by_id = AsyncMock(return_value=player)
        handler.storage_ring_manager.has_item = MagicMock(return_value=True)

        event = MagicMock()
        event.get_sender_id.return_value = "u1"
        event.get_message_str.return_value = "装备 烈火诀"
        event.plain_result = MagicMock(return_value="plain")
        async for _ in handler.handle_equip_item(event, "烈火诀"):
            pass

        msg = event.plain_result.call_args[0][0]
        # Should succeed — it becomes study target
        assert "已将" in msg or "设为修习目标" in msg

    @pytest.mark.asyncio
    async def test_learned_technique_is_study_target_rejected(self, handler):
        """Learned technique is rejected with 'activate' hint."""
        player = FakePlayer(
            user_id="u1",
            techniques="[]",
            storage_ring_items='{"基础吐纳": 1}',
        )
        handler.skill_manager.learned_skills = {"common_001"}
        handler.db.get_player_by_id = AsyncMock(return_value=player)
        handler.storage_ring_manager.has_item = MagicMock(return_value=True)

        event = MagicMock()
        event.get_sender_id.return_value = "u1"
        event.get_message_str.return_value = "装备 基础吐纳"
        event.plain_result = MagicMock(return_value="plain")
        async for _ in handler.handle_equip_item(event, "基础吐纳"):
            pass

        msg = event.plain_result.call_args[0][0]
        # Should be rejected with "激活功法" hint
        assert "已领悟" in msg and "激活功法" in msg
