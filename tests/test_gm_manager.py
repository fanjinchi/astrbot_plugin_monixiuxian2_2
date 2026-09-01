"""Tests for GMManager."""

import json
import random
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tests.helpers import load_module, load_package_module

# Load gm_manager without triggering the plugin's __init__.py chain
_mod = load_module("gm_manager", "core/gm_manager.py")
GMManager = _mod.GMManager
LOG_MAX_SIZE_BYTES = _mod.LOG_MAX_SIZE_BYTES

_migration_mod = load_module("migration_gm_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_data_mod = load_package_module(
    "data/data_manager.py", "astrbot_plugin_monixiuxian2_2.data.data_manager"
)
DataBase = _data_mod.DataBase


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
    spirit_names = [
        "练气一阶",
        "练气二阶",
        "练气三阶",
        "练气四阶",
        "练气五阶",
        "练气六阶",
        "练气七阶",
        "练气八阶",
        "练气九阶",
        "筑基初期",
    ]
    body_names = [
        "练气一阶",
        "练气二阶",
        "练气三阶",
        "练气四阶",
        "练气五阶",
        "练气六阶",
        "练气七阶",
        "练气八阶",
        "练气九阶",
        "筑基初期",
    ]
    cm.level_data = [
        {"level": i + 1, "level_name": name} for i, name in enumerate(spirit_names)
    ]
    cm.body_level_data = [
        {"level": i + 1, "level_name": name} for i, name in enumerate(body_names)
    ]
    cm.items_data = {"灵草": {"name": "灵草"}, "青锋剑": {"name": "青锋剑"}}
    cm.weapons_data = {"青锋剑": {"name": "青锋剑"}}
    cm.pills_data = {}
    cm.exp_pills_data = {}
    cm.utility_pills_data = {}
    cm.storage_rings_data = {}
    cm.heart_methods_data = {"长春功": {"name": "长春功"}}

    def get_level_name(level_index, cultivation_type="灵修"):
        data = cm.body_level_data if cultivation_type == "体修" else cm.level_data
        if 1 <= level_index <= len(data):
            return data[level_index - 1]["level_name"]
        return f"境界{level_index}"

    def get_level_index_by_name(name, cultivation_type="灵修"):
        data = cm.body_level_data if cultivation_type == "体修" else cm.level_data
        for i, entry in enumerate(data):
            if entry.get("level_name") == name:
                return i + 1
        return None

    def get_max_level(cultivation_type="灵修"):
        return len(cm.body_level_data if cultivation_type == "体修" else cm.level_data)

    cm.get_level_name = get_level_name
    cm.get_level_index_by_name = get_level_index_by_name
    cm.get_max_level = get_max_level
    cm.get_level_data = MagicMock(return_value=cm.level_data)
    cm.get_exp_needed = MagicMock(return_value=1000)
    cm.get_success_rate = MagicMock(return_value=0.5)
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
    """Build a minimal Player-like object with new four-main-attribute framework."""
    from tests.helpers import load_module

    _models = load_module("models_for_gm", "models.py")
    return _models.Player(
        user_id=user_id,
        user_name=user_name,
        cultivation_type=cultivation_type,
        level_index=0,
        experience=0,
        gold=100,
        damage=10,
        agility=5,
        speed=5,
        hp=100,
        armor_value=0,
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
        success, msg = await gm_manager.cmd_set_level(event, "筑基初期")

        assert success is True
        assert player.level_index == 10
        assert "筑基初期" in msg
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

    @pytest.mark.asyncio
    async def test_set_mp_maps_to_speed(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_mp(event, "500")

        assert success is True
        assert player.speed == 500

    @pytest.mark.asyncio
    async def test_set_atk_maps_to_damage(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_atk(event, "999")

        assert success is True
        assert player.damage == 999

    @pytest.mark.asyncio
    async def test_set_mental_power_maps_to_agility(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_set_mental_power(event, "123")

        assert success is True
        assert player.agility == 123

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

    @pytest.mark.asyncio
    async def test_give_heart_method(self, gm_manager, mock_db, mock_managers):
        """Regression (bd 7px): heart methods must pass _item_exists validation."""
        player = make_player()
        mock_db.get_player_by_id.return_value = player
        mock_managers["storage_ring_manager"].store_item = AsyncMock(
            return_value=(True, "")
        )

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_give_item(event, "长春功")

        assert success is True
        assert "长春功" in msg
        mock_managers["storage_ring_manager"].store_item.assert_awaited_once_with(
            player, "长春功", 1, silent=True
        )


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


class TestClearBounty:
    """GM「清除悬赏」：清除进行中悬赏记录与放弃冷却（system_config 键置过期）。"""

    @pytest.mark.asyncio
    async def test_clear_bounty_requires_confirmation(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player
        # 确认门槛必须阻断一切副作用，防门槛回归后"假拒绝真清除"——先装好探针再触发
        mock_db.ext.cancel_bounty = AsyncMock()
        mock_db.ext.set_system_config = AsyncMock()

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_clear_bounty(event, "12345")

        assert success is False
        assert "确认" in msg
        mock_db.ext.cancel_bounty.assert_not_awaited()
        mock_db.ext.set_system_config.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clear_bounty_clears_active_and_cooldown(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player
        mock_db.ext.get_active_bounty = AsyncMock(
            return_value={"bounty_id": 901, "bounty_name": "后山巡视"}
        )
        mock_db.ext.cancel_bounty = AsyncMock()
        mock_db.ext.get_system_config = AsyncMock(return_value="9999999999")
        mock_db.ext.set_system_config = AsyncMock()

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_clear_bounty(event, "12345 确认")

        assert success is True
        assert "后山巡视" in msg and "放弃冷却" in msg
        mock_db.ext.cancel_bounty.assert_awaited_once_with("12345")
        mock_db.ext.set_system_config.assert_awaited_once_with(
            "bounty_abandon_cd_12345", "0"
        )

    @pytest.mark.asyncio
    async def test_clear_bounty_nothing_to_clear(self, gm_manager, mock_db):
        player = make_player()
        mock_db.get_player_by_id.return_value = player
        mock_db.ext.get_active_bounty = AsyncMock(return_value=None)
        mock_db.ext.cancel_bounty = AsyncMock()
        mock_db.ext.get_system_config = AsyncMock(return_value=None)
        mock_db.ext.set_system_config = AsyncMock()

        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_clear_bounty(event, "12345 确认")

        assert success is False
        assert "没有可清除" in msg
        mock_db.ext.cancel_bounty.assert_not_awaited()
        mock_db.ext.set_system_config.assert_not_awaited()


# ===== GM 传承子命令（给予传承 / 清除传承） =====


class _FakeLegacyInstance:
    """Minimal legacy instance stub for GM legacy tests."""

    def __init__(self, id, owner_id, legacy_type="common", sect_id=None):
        self.id = id
        self.owner_id = owner_id
        self.legacy_type = legacy_type
        self.sect_id = sect_id
        self.is_active = 0


class _FakeImpartManager:
    """Stub ImpartManager: create_legacy + get_type_name."""

    def __init__(self):
        self._next_id = 1
        self.created = []

    async def create_legacy(
        self, owner_id, legacy_type, sect_id=None, activate=False, commit=True
    ):
        inst = _FakeLegacyInstance(self._next_id, owner_id, legacy_type, sect_id)
        self._next_id += 1
        self.created.append(inst)
        return inst

    def get_type_name(self, legacy_type):
        return {
            "common": "通用传承",
            "sect": "宗门传承",
            "adventure": "历练传承",
            "rift": "秘境传承",
        }[legacy_type]


def _wire_legacy(gm_manager, mock_db, storage=None):
    """Attach a fake impart manager and an in-memory legacy store to the GM fixture."""
    fake = _FakeImpartManager()
    store = storage if storage is not None else []
    fake.created = store  # create_legacy 与 DAO 共用同一存储
    # 预置 store 时同步 ID 计数器，避免后续 create_legacy 复用已存在编号
    if store:
        fake._next_id = max(i.id for i in store) + 1
    gm_manager.impart_manager = fake

    async def _list_by_owner(owner_id):
        return [i for i in store if i.owner_id == owner_id]

    async def _delete(instance_id):
        store[:] = [i for i in store if i.id != instance_id]

    mock_db.ext.list_legacy_instances_by_owner = AsyncMock(side_effect=_list_by_owner)
    mock_db.ext.delete_legacy_instance = AsyncMock(side_effect=_delete)
    return store


@pytest.mark.asyncio
async def test_give_legacy_default_and_typed(gm_manager, mock_db):
    """给予传承：默认 common；指定 adventure 生效；中文别名生效；非法类型拒绝。"""
    store = _wire_legacy(gm_manager, mock_db)
    mock_db.get_player_by_id.return_value = make_player(user_id="900000002")
    event = make_event("给予传承 900000002")

    # 省略目标与类型：作用于发送者自身，默认 common
    ok, msg = await gm_manager.cmd_give_legacy(make_event(sender_id="900000002"), "")
    assert ok and "通用传承" in msg and store[-1].legacy_type == "common"

    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002 adventure")
    assert ok and "历练传承" in msg and store[-1].legacy_type == "adventure"

    # 单 token 数字视为目标（给予传承 900000002）
    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002")
    assert ok and "通用传承" in msg and store[-1].legacy_type == "common"

    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002 秘境")
    assert ok and store[-1].legacy_type == "rift"

    store_len = len(store)
    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002 foo")
    assert not ok and "可选" in msg
    # 非法类型不得创建实例（校验必须先于创建）
    assert len(store) == store_len, "非法类型不应创建传承实例"


@pytest.mark.asyncio
async def test_give_sect_legacy_binds_current_sect(gm_manager, mock_db):
    """给予 sect 类型时自动绑定目标玩家当前宗门；无宗门时拒绝+提示。"""
    store = _wire_legacy(gm_manager, mock_db)
    player = make_player(user_id="900000002")
    player.sect_id = 7
    mock_db.get_player_by_id.return_value = player
    event = make_event("给予传承 900000002 sect")

    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002 sect")
    assert ok
    assert store[-1].legacy_type == "sect" and store[-1].sect_id == 7

    # 无宗门玩家：拒绝创建，不产生游离宗门传承（sect-system 不变式）
    player.sect_id = 0
    ok, msg = await gm_manager.cmd_give_legacy(event, "900000002 sect")
    assert not ok and "无宗门" in msg
    assert len(store) == 1, "不应创建任何实例"


@pytest.mark.asyncio
async def test_clear_legacy_state(gm_manager, mock_db):
    """清除传承状态：删除挑战冷却与保护期，返回条数。"""
    mock_db.get_player_by_id.return_value = make_player(user_id="900000002")
    gm_manager.impart_manager = _FakeImpartManager()
    mock_db.ext.delete_impart_pk_cooldowns = AsyncMock(return_value=2)
    mock_db.ext.delete_impart_snatch_protection = AsyncMock(return_value=1)
    event = make_event(sender_id="gm_001")

    # 单 token 数字目标（spec 原文「清除传承状态 900000002」）：
    # _resolve_target 的 single_token_is_target 参数使之可直接作为目标 ID
    ok, msg = await gm_manager.cmd_clear_legacy_state(event, "900000002")
    assert ok and "挑战冷却 2 条" in msg and "保护期 1 条" in msg
    mock_db.ext.delete_impart_pk_cooldowns.assert_awaited_once_with("900000002")
    mock_db.ext.delete_impart_snatch_protection.assert_awaited_once_with("900000002")

    # 无目标（省略）时作用于发送者
    mock_db.ext.delete_impart_pk_cooldowns.reset_mock()
    mock_db.ext.delete_impart_snatch_protection.reset_mock()
    mock_db.get_player_by_id.reset_mock()
    mock_db.get_player_by_id.return_value = make_player(user_id="gm_001")
    ok, msg = await gm_manager.cmd_clear_legacy_state(event, "")
    assert ok
    mock_db.ext.delete_impart_pk_cooldowns.assert_awaited_once_with("gm_001")


@pytest.mark.asyncio
async def test_clear_legacy_all_and_by_id(gm_manager, mock_db):
    """清除传承：无编号删全部；指定编号只删该条；非本人编号拒绝。"""
    mock_db.get_player_by_id.return_value = make_player(user_id="900000002")
    store = _wire_legacy(
        gm_manager,
        mock_db,
        storage=[
            _FakeLegacyInstance(1, "900000002"),
            _FakeLegacyInstance(2, "900000002", "adventure"),
            _FakeLegacyInstance(3, "other_user"),
        ],
    )
    event = make_event("清除传承 900000002")

    # 删除指定编号
    ok, msg = await gm_manager.cmd_clear_legacy(event, "900000002 1")
    assert ok and "#1" in msg
    assert [i.id for i in store] == [2, 3]

    # 非本人编号拒绝且不产生变更
    ok, msg = await gm_manager.cmd_clear_legacy(event, "900000002 3")
    assert not ok and "未持有" in msg
    assert [i.id for i in store] == [2, 3]

    # 「全部」关键字删该玩家全部
    ok, msg = await gm_manager.cmd_clear_legacy(event, "900000002 全部")
    assert ok and "共 1 条" in msg
    assert [i.id for i in store] == [3]

    # 先还原一条再测无编号删全部
    store.append(_FakeLegacyInstance(4, "900000002"))
    ok, msg = await gm_manager.cmd_clear_legacy(make_event(sender_id="900000002"), "")
    assert ok and "共 1 条" in msg
    assert [i.id for i in store] == [3]

    # 空持有拒绝
    ok, msg = await gm_manager.cmd_clear_legacy(make_event(sender_id="900000002"), "")
    assert not ok and "未持有任何传承" in msg


# ===== GM 测试工具子命令（时间快进 / 清除全部冷却 / 随机种子） =====
# OpenSpec change: gm-test-time-and-rng-controls


@pytest_asyncio.fixture
async def real_db():
    """Provide a migrated in-memory database and close it after the test."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, MagicMock()).migrate()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def gm_real_db(real_db, mock_config_manager, plugin_data_dir):
    """GMManager backed by a real in-memory DB; peripheral managers stay mocked."""
    adventure = MagicMock()
    adventure._route_cooldowns = {}
    return GMManager(
        db=real_db,
        config_manager=mock_config_manager,
        storage_ring_manager=MagicMock(),
        equipment_manager=MagicMock(),
        adventure_manager=adventure,
        rift_manager=None,
        boss_manager=None,
        bounty_manager=None,
        plugin_data_path=plugin_data_dir,
    )


async def _seed_time_skip_domains(db, now):
    """Insert one covered row per 时间快进 domain plus control rows that must
    stay untouched (IDLE user_cd, non-cultivating player, inactive records,
    non-numeric system_config value)."""
    await db.ext.set_user_busy("u_adv", 2, now + 3600)  # 历练中
    await db.ext.set_user_free("u_idle")  # IDLE 行 scheduled_time=0，不应前移
    await db.conn.execute(
        "INSERT INTO players (user_id, user_name, state, cultivation_start_time) "
        "VALUES ('u_cult', '闭关道友', '修炼中', ?)",
        (now - 60,),
    )
    await db.conn.execute(
        "INSERT INTO players (user_id, user_name, state, cultivation_start_time) "
        "VALUES ('u_free', '闲云野鹤', '空闲', ?)",
        (now - 60,),
    )
    await db.conn.execute(
        "INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time) "
        "VALUES ('u_pvp', ?, ?)",
        (now - 100, now - 50),
    )
    await db.conn.execute(
        "INSERT INTO dual_cultivation (user_id, last_dual_time) VALUES ('u_dual', ?)",
        (now - 200,),
    )
    await db.conn.execute(
        "INSERT INTO bounty_tasks (user_id, bounty_id, bounty_name, target_type, "
        "target_count, rewards, start_time, expire_time, status) "
        "VALUES ('u_bounty', 301, '后山巡视', 'adventure', 3, '{}', ?, ?, 1)",
        (now - 10, now + 7200),
    )
    await db.conn.execute(
        "INSERT INTO bounty_tasks (user_id, bounty_id, bounty_name, target_type, "
        "target_count, rewards, start_time, expire_time, status) "
        "VALUES ('u_bounty_done', 302, '已结算悬赏', 'adventure', 1, '{}', ?, ?, 0)",
        (now - 5000, now - 4000),
    )
    await db.conn.execute(
        "INSERT INTO bank_loans (user_id, principal, borrowed_at, due_at, status) "
        "VALUES ('u_loan', 1000, ?, ?, 'active')",
        (now - 1000, now + 86400),
    )
    await db.conn.execute(
        "INSERT INTO bank_loans (user_id, principal, borrowed_at, due_at, status) "
        "VALUES ('u_repaid', 1000, ?, ?, 'repaid')",
        (now - 9000, now - 8000),
    )
    await db.ext.set_system_config("bounty_abandon_cd_u_bounty", str(now + 1800))
    await db.ext.set_system_config("boss_next_spawn_time", str(now + 600))
    # 已过期字段：前移只会更深地留在过去，不会倒排到未来
    await db.ext.set_system_config("spirit_eye_next_spawn_time", str(now - 100))
    await db.ext.set_system_config("unrelated_key", "not_a_timestamp")
    await db.conn.execute(
        "INSERT INTO impart_pk_cooldown (challenger_id, target_id, failed_at) "
        "VALUES ('u_challenger', 'u_target', ?)",
        (now - 300,),
    )
    await db.conn.execute(
        "INSERT INTO impart_snatch_protection (user_id, snatched_at) "
        "VALUES ('u_snatched', ?)",
        (now - 400,),
    )
    await db.conn.commit()


class TestTimeSkip:
    """GM「时间快进」：确认约定、参数校验、逐域前移量与回复条数。"""

    @pytest.mark.asyncio
    async def test_requires_confirmation_with_zero_side_effects(
        self, gm_real_db, real_db
    ):
        now = int(time.time())
        await _seed_time_skip_domains(real_db, now)

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_time_skip(event, "3600")

        assert success is False
        assert "确认" in msg
        cd = await real_db.ext.get_user_cd("u_adv")
        assert cd.scheduled_time == now + 3600
        assert await real_db.ext.get_system_config("boss_next_spawn_time") == str(
            now + 600
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "3.5", ""])
    async def test_invalid_seconds_rejected(self, gm_real_db, real_db, bad):
        now = int(time.time())
        await _seed_time_skip_domains(real_db, now)

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_time_skip(event, f"{bad} 确认")

        assert success is False
        assert "正整数" in msg
        cd = await real_db.ext.get_user_cd("u_adv")
        assert cd.scheduled_time == now + 3600

    @pytest.mark.asyncio
    async def test_skip_shifts_all_domains(self, gm_real_db, real_db):
        now = int(time.time())
        await _seed_time_skip_domains(real_db, now)

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_time_skip(event, "3600 确认")
        assert success is True

        # user_cd：忙碌记录前移，IDLE 记录不动
        cd = await real_db.ext.get_user_cd("u_adv")
        assert cd.scheduled_time == now + 3600 - 3600
        idle = await real_db.ext.get_user_cd("u_idle")
        assert idle.scheduled_time == 0

        # players：仅闭关（修炼中）玩家前移
        async with real_db.conn.execute(
            "SELECT state, cultivation_start_time FROM players "
            "WHERE user_id IN ('u_cult', 'u_free')"
        ) as cur:
            rows = {r[0]: r[1] async for r in cur}
        assert rows["修炼中"] == now - 60 - 3600
        assert rows["空闲"] == now - 60

        # combat_cooldowns：两个字段同时前移
        async with real_db.conn.execute(
            "SELECT last_duel_time, last_spar_time FROM combat_cooldowns "
            "WHERE user_id = 'u_pvp'"
        ) as cur:
            duel, spar = await cur.fetchone()
        assert duel == now - 100 - 3600
        assert spar == now - 50 - 3600

        # 双修冷却
        async with real_db.conn.execute(
            "SELECT last_dual_time FROM dual_cultivation WHERE user_id = 'u_dual'"
        ) as cur:
            (dual_time,) = await cur.fetchone()
        assert dual_time == now - 200 - 3600

        # bounty_tasks：仅进行中（status=1）前移
        async with real_db.conn.execute(
            "SELECT user_id, expire_time FROM bounty_tasks"
        ) as cur:
            bounties = {r[0]: r[1] async for r in cur}
        assert bounties["u_bounty"] == now + 7200 - 3600
        assert bounties["u_bounty_done"] == now - 4000

        # bank_loans：仅 active 前移
        async with real_db.conn.execute(
            "SELECT user_id, due_at FROM bank_loans"
        ) as cur:
            loans = {r[0]: r[1] async for r in cur}
        assert loans["u_loan"] == now + 86400 - 3600
        assert loans["u_repaid"] == now - 8000

        # system_config 三键；非时间戳键不动；已过期字段不倒排到未来
        assert await real_db.ext.get_system_config("bounty_abandon_cd_u_bounty") == str(
            now + 1800 - 3600
        )
        assert await real_db.ext.get_system_config("boss_next_spawn_time") == str(
            now + 600 - 3600
        )
        eye = int(await real_db.ext.get_system_config("spirit_eye_next_spawn_time"))
        assert eye == now - 100 - 3600 < now
        assert await real_db.ext.get_system_config("unrelated_key") == "not_a_timestamp"

        # 传承：挑战冷却与被夺保护期
        failed_at = await real_db.ext.get_impart_pk_cooldown("u_challenger", "u_target")
        assert failed_at == now - 300 - 3600
        snatched_at = await real_db.ext.get_impart_snatch_protection("u_snatched")
        assert snatched_at == now - 400 - 3600

        # 回复逐域列出前移条数
        for fragment in (
            "历练/秘境/宗门任务计划完成时间：1 条",
            "闭关开始时间：1 条",
            "决斗/切磋冷却：1 条",
            "双修冷却：1 条",
            "进行中悬赏过期时间：1 条",
            "贷款到期时间：1 条",
            "悬赏放弃冷却：1 条",
            "Boss/灵眼下次刷新时间：2 条",
            "传承挑战冷却：1 条",
            "传承被夺保护期：1 条",
            "共前移 11 条",
        ):
            assert fragment in msg

    def test_commands_registered(self, gm_manager):
        assert gm_manager._commands["时间快进"] == gm_manager.cmd_time_skip
        assert (
            gm_manager._commands["清除全部冷却"] == gm_manager.cmd_clear_all_cooldowns
        )
        assert gm_manager._commands["随机种子"] == gm_manager.cmd_seed


async def _seed_clear_all_domains(db, uid, now):
    """Preset every clearable cooldown domain for the target player."""
    await db.conn.execute(
        "INSERT INTO players (user_id, user_name, state) VALUES (?, '道友', '历练中')",
        (uid,),
    )
    await db.ext.set_user_busy(uid, 2, now + 3600)  # 历练中
    await db.conn.execute(
        "INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time) "
        "VALUES (?, ?, ?)",
        (uid, now - 10, now - 5),
    )
    await db.conn.execute(
        "INSERT INTO dual_cultivation (user_id, last_dual_time) VALUES (?, ?)",
        (uid, now - 30),
    )
    await db.ext.create_bounty(uid, 301, "后山巡视", "adventure", 3, "{}", now + 7200)
    await db.ext.set_system_config(f"bounty_abandon_cd_{uid}", str(now + 1800))
    await db.ext.upsert_impart_pk_cooldown(uid, "someone", now - 60)
    await db.ext.upsert_impart_snatch_protection(uid, now - 120)
    await db.conn.commit()


class TestClearAllCooldowns:
    """GM「清除全部冷却」：确认约定、逐域归零、空状态提示。"""

    @pytest.mark.asyncio
    async def test_requires_confirmation_with_zero_side_effects(
        self, gm_real_db, real_db
    ):
        uid = "900000002"
        now = int(time.time())
        await _seed_clear_all_domains(real_db, uid, now)
        gm_real_db.adventure_manager._route_cooldowns[uid] = {"route_a": now + 300}

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_clear_all_cooldowns(event, uid)

        assert success is False
        assert "确认" in msg
        cd = await real_db.ext.get_user_cd(uid)
        assert cd.type != 0
        assert (await real_db.ext.get_active_bounty(uid)) is not None
        assert uid in gm_real_db.adventure_manager._route_cooldowns

    @pytest.mark.asyncio
    async def test_clears_all_domains(self, gm_real_db, real_db):
        uid = "900000002"
        now = int(time.time())
        await _seed_clear_all_domains(real_db, uid, now)
        gm_real_db.adventure_manager._route_cooldowns[uid] = {"route_a": now + 300}

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_clear_all_cooldowns(event, f"{uid} 确认")
        assert success is True

        # user_cd 空闲 + player.state 同步复位
        cd = await real_db.ext.get_user_cd(uid)
        assert cd.type == 0
        player = await real_db.get_player_by_id(uid)
        assert player.state == "空闲"

        # 决斗/切磋可立即发起
        async with real_db.conn.execute(
            "SELECT last_duel_time, last_spar_time FROM combat_cooldowns "
            "WHERE user_id = ?",
            (uid,),
        ) as cur:
            duel, spar = await cur.fetchone()
        assert duel == 0 and spar == 0

        # 双修冷却归零
        async with real_db.conn.execute(
            "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?", (uid,)
        ) as cur:
            (dual_time,) = await cur.fetchone()
        assert dual_time == 0

        # 悬赏可立即接取：无进行中悬赏 + 放弃冷却置 "0"
        assert (await real_db.ext.get_active_bounty(uid)) is None
        assert await real_db.ext.get_system_config(f"bounty_abandon_cd_{uid}") == "0"

        # 传承挑战冷却/被夺保护期删除
        assert (await real_db.ext.get_impart_pk_cooldown(uid, "someone")) is None
        assert (await real_db.ext.get_impart_snatch_protection(uid)) is None

        # 历练路线休整冷却（内存）弹出
        assert uid not in gm_real_db.adventure_manager._route_cooldowns

        for fragment in (
            "忙碌状态：1 条",
            "决斗/切磋冷却：1 条",
            "双修冷却：1 条",
            "进行中悬赏：1 条（后山巡视）",
            "悬赏放弃冷却：1 条",
            "传承挑战冷却：1 条",
            "传承被夺保护期：1 条",
            "历练路线休整冷却：1 条",
        ):
            assert fragment in msg

    @pytest.mark.asyncio
    async def test_nothing_to_clear(self, gm_real_db, real_db):
        uid = "900000003"
        await real_db.conn.execute(
            "INSERT INTO players (user_id, user_name, state) "
            "VALUES (?, '闲人', '空闲')",
            (uid,),
        )
        await real_db.conn.commit()

        event = make_event(sender_id="gm_001")
        success, msg = await gm_real_db.cmd_clear_all_cooldowns(event, f"{uid} 确认")

        assert success is False
        assert "没有可清除" in msg
        # 无副作用：不生成任何悬赏冷却键或 user_cd 行
        assert (await real_db.ext.get_system_config(f"bounty_abandon_cd_{uid}")) is None
        assert (await real_db.ext.get_user_cd(uid)) is None


@pytest.fixture
def restore_random():
    """Reset global RNG entropy after each seed test so a fixed sequence never
    leaks into other tests (种子不持久化约定在测试侧的镜像)。"""
    yield
    random.seed()


class TestSeed:
    """GM「随机种子」：固定可复现、重置恢复、非法参数保持随机状态。"""

    @pytest.mark.asyncio
    async def test_fixed_seed_reproducible(self, gm_manager, restore_random):
        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_seed(event, "42")
        assert success is True
        assert "42" in msg
        assert "仅限测试场景" in msg and "进程级" in msg

        seq1 = [random.random() for _ in range(8)]
        await gm_manager.cmd_seed(event, "42")
        seq2 = [random.random() for _ in range(8)]
        assert seq1 == seq2

    @pytest.mark.asyncio
    async def test_reset_restores_entropy(self, gm_manager, restore_random):
        event = make_event(sender_id="gm_001")
        await gm_manager.cmd_seed(event, "42")
        fixed_seq = [random.random() for _ in range(8)]

        success, msg = await gm_manager.cmd_seed(event, "重置")
        assert success is True
        assert "系统熵" in msg

        seq = [random.random() for _ in range(8)]
        # 重置后不再按固定序列产出（8 个 53-bit 浮点全相同的概率可忽略）
        assert seq != fixed_seq

    @pytest.mark.asyncio
    async def test_invalid_param_keeps_random_state(self, gm_manager, restore_random):
        event = make_event(sender_id="gm_001")
        await gm_manager.cmd_seed(event, "123")
        state_before = random.getstate()

        success, msg = await gm_manager.cmd_seed(event, "abc")
        assert success is False
        assert "参数错误" in msg
        assert random.getstate() == state_before

        success, _ = await gm_manager.cmd_seed(event, "")
        assert success is False
        assert random.getstate() == state_before

    @pytest.mark.asyncio
    async def test_seed_logged_via_dispatch(
        self, gm_manager, plugin_data_dir, restore_random
    ):
        event = make_event(sender_id="gm_001")
        success, _ = await gm_manager.dispatch("gm_001", event, "随机种子", "42")
        assert success is True

        content = (
            (plugin_data_dir / "gm_operations.log").read_text(encoding="utf-8").strip()
        )
        entry = json.loads(content)
        assert entry["command"] == "随机种子"
        assert entry["args"] == "42"
        assert entry["gm_user_id"] == "gm_001"
        assert entry["success"] is True

    @pytest.mark.asyncio
    async def test_help_lists_test_commands(self, gm_manager):
        event = make_event(sender_id="gm_001")
        success, msg = await gm_manager.cmd_help(event, "")
        assert success is True
        for fragment in ("时间快进", "清除全部冷却", "随机种子", "仅限测试实例"):
            assert fragment in msg
