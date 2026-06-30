"""Tests for GMManager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import load_module

# Load gm_manager without triggering the plugin's __init__.py chain
_mod = load_module("gm_manager", "core/gm_manager.py")
GMManager = _mod.GMManager
LOG_MAX_SIZE_BYTES = _mod.LOG_MAX_SIZE_BYTES


class At(MagicMock):
    """Mock an AstrBot At (mention) message segment."""

    pass


@pytest.fixture
def plugin_data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def mock_config_manager():
    cm = MagicMock()
    cm.level_data = [
        {"level_name": "炼气期一层"},
        {"level_name": "炼气期二层"},
        {"level_name": "筑基期初期"},
    ]
    cm.body_level_data = [
        {"level_name": "炼体一层"},
        {"level_name": "炼体二层"},
    ]
    cm.items_data = {"灵草": {"name": "灵草"}, "青锋剑": {"name": "青锋剑"}}
    cm.weapons_data = {"青锋剑": {"name": "青锋剑"}}
    cm.get_level_data = MagicMock(return_value=cm.level_data)
    return cm


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_player_by_id = AsyncMock()
    db.update_player = AsyncMock()

    ext = MagicMock()
    ext.get_user_cd = AsyncMock()
    ext.set_user_free = AsyncMock()
    ext.update_user_cd = AsyncMock()
    db.ext = ext
    return db


@pytest.fixture
def mock_managers():
    return {
        "storage_ring_manager": MagicMock(),
        "equipment_manager": MagicMock(),
        "adventure_manager": MagicMock(),
        "rift_manager": MagicMock(),
        "boss_manager": MagicMock(),
        "bounty_manager": MagicMock(),
    }


@pytest.fixture
def gm_manager(mock_db, mock_config_manager, mock_managers, plugin_data_dir):
    mgr = GMManager(
        db=mock_db,
        config_manager=mock_config_manager,
        storage_ring_manager=mock_managers["storage_ring_manager"],
        equipment_manager=mock_managers["equipment_manager"],
        adventure_manager=mock_managers["adventure_manager"],
        rift_manager=mock_managers["rift_manager"],
        boss_manager=mock_managers["boss_manager"],
        bounty_manager=mock_managers["bounty_manager"],
        plugin_data_path=plugin_data_dir,
    )
    return mgr


def make_player(user_id="12345", user_name="测试道友", cultivation_type="灵修"):
    """Build a minimal Player-like object."""
    from tests.helpers import load_module

    _models = load_module("models_for_gm", "models.py")
    return _models.Player(
        user_id=user_id,
        user_name=user_name,
        cultivation_type=cultivation_type,
        level_index=0,
        experience=0,
        gold=100,
        hp=100,
        mp=50,
        atk=10,
        mental_power=100,
        weapon="青锋剑",
        armor="",
        main_technique="",
        techniques="[]",
        state="空闲",
        storage_ring_items="{}",
    )


def make_event(sender_id="gm_001", mentions=None, message_text=""):
    """Build a minimal AstrMessageEvent-like object."""
    event = MagicMock()
    event.get_sender_id.return_value = sender_id
    event.get_message_str.return_value = message_text

    ats = mentions or []
    message_obj = MagicMock()
    message_obj.message = ats
    event.message_obj = message_obj
    return event


class TestTargetResolution:
    def test_default_to_sender(self, gm_manager):
        event = make_event(sender_id="self_id")
        target_id, remaining = gm_manager._resolve_target(event, "1000")
        assert target_id == "self_id"
        assert remaining == "1000"

    def test_numeric_target(self, gm_manager):
        event = make_event(sender_id="self_id")
        target_id, remaining = gm_manager._resolve_target(event, "99999 1000")
        assert target_id == "99999"
        assert remaining == "1000"

    def test_at_mention_target(self, gm_manager):
        at = At()
        at.qq = "88888"
        event = make_event(sender_id="self_id", mentions=[at])
        target_id, remaining = gm_manager._resolve_target(event, "@玩家 1000")
        assert target_id == "88888"
        assert remaining == "1000"

    def test_at_mention_target_without_text(self, gm_manager):
        """平台不将 At 渲染为文本时，不能误删后续参数。"""
        at = At()
        at.qq = "88888"
        event = make_event(sender_id="self_id", mentions=[at])
        target_id, remaining = gm_manager._resolve_target(event, "1000")
        assert target_id == "88888"
        assert remaining == "1000"


class TestSetLevel:
    @pytest.mark.asyncio
    async def test_set_level_success(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_level(event, "筑基期初期")

        assert success is True
        assert player.level_index == 2
        assert "筑基期初期" in msg
        mock_db.update_player.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_level_invalid(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_level(event, "不存在")

        assert success is False
        assert "未找到境界" in msg


class TestSetNumericAttributes:
    @pytest.mark.asyncio
    async def test_set_gold(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_gold(event, "9999")

        assert success is True
        assert player.gold == 9999
        assert "9,999" in msg

    @pytest.mark.asyncio
    async def test_set_hp(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_hp(event, "500")

        assert success is True
        assert player.hp == 500

    @pytest.mark.asyncio
    async def test_set_gold_with_at_mention(self, gm_manager, mock_db):
        player = make_player(user_id="88888")
        mock_db.get_player_by_id.return_value = player

        at = At()
        at.qq = "88888"
        event = make_event(sender_id="gm_001", mentions=[at])
        success, msg = await gm_manager.cmd_set_gold(event, "@玩家 9999")

        assert success is True
        assert player.gold == 9999


class TestGiveItems:
    @pytest.mark.asyncio
    async def test_give_equipment_to_storage_ring(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player()
        mock_db.get_player_by_id.return_value = player
        mock_managers["storage_ring_manager"].store_item = AsyncMock(
            return_value=(True, "")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_give_equipment(event, "青锋剑")

        assert success is True
        assert "青锋剑" in msg
        mock_managers["storage_ring_manager"].store_item.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_give_unknown_item(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_give_equipment(event, "不存在的物品")

        assert success is False
        assert "不存在" in msg


class TestClearCD:
    @pytest.mark.asyncio
    async def test_clear_cd_requires_confirmation(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_clear_cd(event, "12345")

        assert success is False
        assert "确认" in msg

    @pytest.mark.asyncio
    async def test_clear_cd_success(self, gm_manager, mock_db):
        player = make_player()
        player.state = "历练中"
        mock_db.get_player_by_id.return_value = player

        user_cd = MagicMock()
        user_cd.type = 2  # ADVENTURING
        mock_db.ext.get_user_cd.return_value = user_cd

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_clear_cd(event, "12345 确认")

        assert success is True
        assert player.state == "空闲"
        mock_db.ext.set_user_free.assert_awaited_once()
        mock_db.update_player.assert_awaited_once()


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_log_entry_written(self, gm_manager, plugin_data_dir, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        await gm_manager.dispatch("gm_001", event, "设置灵石", "500")

        log_path = plugin_data_dir / "gm_operations.log"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["gm_user_id"] == "gm_001"
        assert entry["target_user_id"] == "gm_001"
        assert entry["command"] == "设置灵石"
        assert entry["success"] is True

    def test_log_rotation(self, gm_manager, plugin_data_dir):
        log_path = plugin_data_dir / "gm_operations.log"
        # Create a log file that exceeds the rotation threshold
        log_path.write_bytes(b"x" * (LOG_MAX_SIZE_BYTES + 1))

        gm_manager._rotate_log_if_needed(log_path)

        # Original log should be rotated away
        assert not log_path.exists()
        rotated = list(plugin_data_dir.glob("gm_operations_*.log"))
        assert len(rotated) == 1
        assert rotated[0].stat().st_size > LOG_MAX_SIZE_BYTES

    @pytest.mark.asyncio
    async def test_failed_operation_logged(self, gm_manager, plugin_data_dir, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        await gm_manager.dispatch("gm_001", event, "设置灵石", "not_a_number")

        log_path = plugin_data_dir / "gm_operations.log"
        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["success"] is False


class TestSpawnBoss:
    @pytest.mark.asyncio
    async def test_spawn_boss_triggers_broadcast(self, gm_manager, mock_managers):
        boss = MagicMock()
        boss.boss_name = "测试Boss"
        mock_managers["boss_manager"].auto_spawn_boss = AsyncMock(
            return_value=(True, "", boss)
        )
        callback = AsyncMock()
        gm_manager.broadcast_callback = callback

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_spawn_boss(event, "")

        assert success is True
        assert "测试Boss" in msg
        callback.assert_awaited_once_with(boss)


class TestForceSettlement:
    @pytest.mark.asyncio
    async def test_force_adventure_updates_bounty_progress(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player(user_id="12345")
        mock_db.get_player_by_id.return_value = player

        user_cd = MagicMock()
        user_cd.type = 2  # ADVENTURING
        user_cd.create_time = 0
        user_cd.scheduled_time = 9999999999
        mock_db.ext.get_user_cd.return_value = user_cd

        reward_data = {
            "bounty_tag": "adventure_scout",
            "bounty_progress": 2,
        }
        mock_managers["adventure_manager"].finish_adventure = AsyncMock(
            return_value=(True, "历练完成", reward_data)
        )
        mock_managers["bounty_manager"].add_bounty_progress = AsyncMock(
            return_value=(True, "\n悬赏进度+2")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_force_adventure(event, "12345")

        assert success is True
        assert "历练完成" in msg
        assert "悬赏进度+2" in msg
        mock_managers["bounty_manager"].add_bounty_progress.assert_awaited_once_with(
            player, "adventure_scout", 2
        )
        mock_db.ext.update_user_cd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_adventure_no_bounty_when_no_reward_data(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player(user_id="12345")
        mock_db.get_player_by_id.return_value = player

        user_cd = MagicMock()
        user_cd.type = 2
        user_cd.create_time = 0
        user_cd.scheduled_time = 9999999999
        mock_db.ext.get_user_cd.return_value = user_cd

        mock_managers["adventure_manager"].finish_adventure = AsyncMock(
            return_value=(True, "历练完成", None)
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_force_adventure(event, "12345")

        assert success is True
        mock_managers["bounty_manager"].add_bounty_progress.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_rift_updates_bounty_progress(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player(user_id="12345")
        mock_db.get_player_by_id.return_value = player

        user_cd = MagicMock()
        user_cd.type = 3  # EXPLORING
        user_cd.create_time = 0
        user_cd.scheduled_time = 9999999999
        mock_db.ext.get_user_cd.return_value = user_cd

        reward_data = {"rift_name": "测试秘境"}
        mock_managers["rift_manager"].finish_exploration = AsyncMock(
            return_value=(True, "秘境完成", reward_data)
        )
        mock_managers["bounty_manager"].add_bounty_progress = AsyncMock(
            return_value=(True, "\n悬赏进度+1")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_force_rift(event, "12345")

        assert success is True
        assert "秘境完成" in msg
        assert "悬赏进度+1" in msg
        mock_managers["bounty_manager"].add_bounty_progress.assert_awaited_once_with(
            player, "rift", 1
        )

    @pytest.mark.asyncio
    async def test_force_adventure_fails_when_not_adventuring(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player(user_id="12345")
        mock_db.get_player_by_id.return_value = player

        user_cd = MagicMock()
        user_cd.type = 0  # IDLE
        mock_db.ext.get_user_cd.return_value = user_cd

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_force_adventure(event, "12345")

        assert success is False
        assert "不在历练中" in msg
        mock_managers["adventure_manager"].finish_adventure.assert_not_called()


class TestUnequip:
    @pytest.mark.asyncio
    async def test_unequip_stores_item_in_storage_ring(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player()
        player.weapon = "青锋剑"
        mock_db.get_player_by_id.return_value = player

        mock_managers["equipment_manager"].unequip_item = AsyncMock(
            return_value=(True, "已卸下武器")
        )
        mock_managers["storage_ring_manager"].store_item = AsyncMock(
            return_value=(True, "")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_unequip(event, "武器")

        assert success is True
        mock_managers["equipment_manager"].unequip_item.assert_awaited_once_with(
            player, "武器"
        )
        mock_managers["storage_ring_manager"].store_item.assert_awaited_once_with(
            player, "青锋剑", 1, silent=True
        )

    @pytest.mark.asyncio
    async def test_unequip_fails_when_not_equipped(
        self, gm_manager, mock_db, mock_managers
    ):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        mock_managers["equipment_manager"].unequip_item = AsyncMock(
            return_value=(False, "未装备该物品")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_unequip(event, "心法")

        assert success is False
        assert "未装备" in msg
        mock_managers["storage_ring_manager"].store_item.assert_not_called()


class TestAtDetection:
    def test_non_at_component_is_not_resolved_as_target(self, gm_manager):
        """Security: a non-At component (e.g. Reply, Poke) must not be treated as an At."""

        class Reply(MagicMock):
            pass

        reply = Reply()
        reply.qq = "99999"
        event = make_event(sender_id="self_id", mentions=[reply])
        target_id, remaining = gm_manager._resolve_target(event, "1000")

        # Should fall back to sender since the Reply component is not an At
        assert target_id == "self_id"
        assert remaining == "1000"


class TestDispatchLogging:
    @pytest.mark.asyncio
    async def test_unknown_command_is_logged(self, gm_manager, plugin_data_dir):
        event = make_event(sender_id="gm_001")
        await gm_manager.dispatch("gm_001", event, "不存在的命令", "")

        log_path = plugin_data_dir / "gm_operations.log"
        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["gm_user_id"] == "gm_001"
        assert entry["command"] == "不存在的命令"
        assert entry["success"] is False
        assert "未知" in entry["message"]

    @pytest.mark.asyncio
    async def test_empty_subcommand_is_logged(self, gm_manager, plugin_data_dir):
        event = make_event(sender_id="gm_001")
        await gm_manager.dispatch("gm_001", event, "", "")

        log_path = plugin_data_dir / "gm_operations.log"
        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["gm_user_id"] == "gm_001"
        assert entry["command"] == ""
        assert entry["success"] is False
