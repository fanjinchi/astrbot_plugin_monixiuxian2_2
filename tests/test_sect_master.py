"""Tests for sect master task chains (师承任务链, change group 5)."""

import pytest
import pytest_asyncio

from tests.helpers import load_module, load_package_module

_migration_mod = load_module("migration_sect_master_test", "data/migration.py")
MigrationManager = _migration_mod.MigrationManager

_data_mod = load_package_module(
    "data/data_manager.py",
    "astrbot_plugin_monixiuxian2_2.data.data_manager",
)
DataBase = _data_mod.DataBase

Player = load_package_module("models.py", "astrbot_plugin_monixiuxian2_2.models").Player

_sect_mod = load_package_module(
    "managers/sect_manager.py",
    "astrbot_plugin_monixiuxian2_2.managers.sect_master_manager",
)
SectManager = _sect_mod.SectManager


def _qingyun_chain():
    """Master task chain mirroring config/sect_tasks.json chain_qy_01."""
    return {
        "id": "chain_qy_01",
        "sect_id": "qingyun",
        "level_range": [0, 2],
        "stages": [
            {
                "name": "入门演武",
                "type": "win_pve",
                "count": 3,
                "reward": {"contribution": 50, "exp": 200},
                "text": "玄诚子：新入门弟子，先去后山演武场活动筋骨，胜三场妖兽来见我。",
            },
            {
                "name": "采药历练",
                "type": "adventure_complete",
                "count": 1,
                "reward": {"contribution": 80, "skill_learn_chance": "sect_qingyun"},
                "text": "玄诚子：丹房缺几味常见灵草，你去历练一趟，顺便把采药的规矩学了。",
            },
            {
                "name": "破境之礼",
                "type": "breakthrough",
                "count": 1,
                "reward": {"contribution": 150, "exp": 1000},
                "text": "清微道长：破境乃修行第一关，成之后来执事堂登记，门中自有嘉奖。",
            },
        ],
    }


def _huanxi_chain():
    """Master task chain mirroring config/sect_tasks.json chain_hx_01.

    Faithful copy of the real config: two stages (投名状 donate 1000 →
    见血 win_pve 5) under level_range [2, 4].
    """
    return {
        "id": "chain_hx_01",
        "sect_id": "huanxi",
        "level_range": [2, 4],
        "stages": [
            {
                "name": "投名状",
                "type": "donate",
                "count": 1000,
                "reward": {"contribution": 80, "exp": 500},
                "text": "花妩娘：入我合欢宗，先纳一千灵石做投名状，宗门不养闲人。",
            },
            {
                "name": "见血",
                "type": "win_pve",
                "count": 5,
                "reward": {"contribution": 120, "skill_learn_chance": "sect_huanxi"},
                "text": "厉无欢：去杀五个不开眼的东西，提着他们的兵刃回来，才算自己人。",
            },
        ],
    }


class FakeConfigManager:
    """Minimal ConfigManager stub for master task chain tests."""

    def __init__(self):
        self.sect_config = {"positions": {}, "scale_ratio": 10}
        self.sect_factions = {
            "factions": [
                {
                    "id": "qingyun",
                    "name": "青云门",
                    "join_level_range": [0, 5],
                    "elders": [{"name": "玄诚子", "title": "传功长老"}],
                },
                {
                    "id": "huanxi",
                    "name": "合欢宗",
                    # 与 config/sect_factions.json 一致
                    "join_level_range": [2, 6],
                    "elders": [{"name": "厉无欢", "title": "护法长老"}],
                },
            ]
        }
        self.sect_tasks = {
            "construction_tasks": [],
            "master_task_chains": [_qingyun_chain(), _huanxi_chain()],
        }
        self.game_config = {
            "skill_system": {
                "max_star": 3,
                "star_compensation_base": 1000,
                "star_compensation_ratio": 0.5,
            }
        }
        self.skills_data = {
            "青云剑诀": {
                "id": "qy_001",
                "name": "青云剑诀",
                "_group": "sect_qingyun",
                "sect_bound": True,
            },
            # 合欢宗功法池桩（真实配置见 config/skills.json sect_huanxi）
            "蚀心魔音": {
                "id": "hx_001",
                "name": "蚀心魔音",
                "_group": "sect_huanxi",
                "sect_bound": True,
            },
        }

    def get_level_name(self, level_index: int, cultivation_type: str = "灵修") -> str:
        return f"境界{level_index}"


@pytest_asyncio.fixture
async def db():
    """Provide a migrated in-memory database and close it after the test."""
    database = DataBase(":memory:")
    await database.connect()
    await MigrationManager(database.conn, FakeConfigManager()).migrate()
    yield database
    await database.close()


async def _make_player(
    db: DataBase, user_id: str, level_index: int = 1, gold: int = 0
) -> Player:
    player = Player(
        user_id=user_id,
        user_name=f"道友{user_id}",
        spiritual_root="天灵根",
        level_index=level_index,
        gold=gold,
    )
    await db.create_player(player)
    return player


async def _join(db, mgr, user_id: str, sect_name: str, level_index: int = 1, gold=0):
    await _make_player(db, user_id, level_index=level_index, gold=gold)
    success, msg = await mgr.join_sect(user_id, sect_name)
    assert success, msg


# ===== 5.1 链匹配与进度存储 =====


@pytest.mark.asyncio
async def test_chain_matched_by_level_range(db):
    """A member sees the chain matching their level range; others see none."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()

    await _join(db, mgr, "u1", "青云门", level_index=1)
    success, msg = await mgr.get_master_task_status("u1")
    assert success, msg
    assert "入门演武" in msg
    assert "0/3" in msg
    assert "玄诚子" in msg  # 长老署名
    assert "贡献+50" in msg  # 奖励预览

    # 超出所有链的境界段（仍在入门招收范围内）
    await _join(db, mgr, "u2", "青云门", level_index=4)
    success, msg = await mgr.get_master_task_status("u2")
    assert not success
    assert "暂无对应的师承任务" in msg

    # 未加入宗门
    await _make_player(db, "u3")
    success, msg = await mgr.get_master_task_status("u3")
    assert not success
    assert "还未加入宗门" in msg


@pytest.mark.asyncio
async def test_player_sect_has_no_master_chain(db):
    """Player-built sects (no faction) have no master tasks."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _make_player(db, "owner", level_index=5, gold=20000)
    success, _ = await mgr.create_sect("owner", "太一宗")
    assert success

    success, msg = await mgr.get_master_task_status("owner")
    assert not success
    assert "暂无师承任务" in msg
    assert await mgr.advance_master_progress("owner", "win_pve") is None


# ===== 5.2 阶段推进与结算 =====


@pytest.mark.asyncio
async def test_win_pve_progress_and_stage_settlement(db):
    """win_pve events advance the stage; reaching count settles it."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=1)

    # 类型不匹配的事件不推进
    assert await mgr.advance_master_progress("u1", "adventure_complete") is None

    msg = await mgr.advance_master_progress("u1", "win_pve")
    assert "入门演武" in msg and "1/3" in msg
    msg = await mgr.advance_master_progress("u1", "win_pve")
    assert "2/3" in msg

    player = await db.get_player_by_id("u1")
    exp_before, contribution_before = player.experience, player.sect_contribution

    # 第三次胜利 -> 阶段结算
    msg = await mgr.advance_master_progress("u1", "win_pve")
    assert "【入门演武】完成" in msg
    assert "玄诚子" in msg  # 长老署名
    assert "宗门贡献 +50" in msg
    assert "修为 +200" in msg
    assert "下一阶段：【采药历练】" in msg

    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == contribution_before + 50
    assert player.experience == exp_before + 200
    progress = player.get_sect_master_progress()
    assert progress == {
        "chain_id": "chain_qy_01",
        "stage_index": 1,
        "progress": 0,
        "done": False,
    }

    # 阶段顺序推进：win_pve 对第二阶段（adventure_complete）无效
    assert await mgr.advance_master_progress("u1", "win_pve") is None


@pytest.mark.asyncio
async def test_breakthrough_stage_survives_level_range_exit(db):
    """An in-progress chain still settles after breakthrough leaves its range."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=2)

    # 推进到最后阶段（突破）
    player = await db.get_player_by_id("u1")
    player.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 2, "progress": 0, "done": False}
    )
    await db.update_player(player)

    # 突破成功使境界超出 level_range [0,2]，链仍应结算
    player = await db.get_player_by_id("u1")
    player.level_index = 3
    await db.update_player(player)

    msg = await mgr.advance_master_progress("u1", "breakthrough")
    assert msg is not None
    assert "【破境之礼】完成" in msg
    assert "师承任务已全部完成" in msg

    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == 150
    assert player.experience == 1000
    assert player.get_sect_master_progress()["done"] is True

    # 完成后不再推进
    assert await mgr.advance_master_progress("u1", "breakthrough") is None

    # 查看指令显示全部完成
    success, msg = await mgr.get_master_task_status("u1")
    assert success
    assert "已全部完成" in msg


@pytest.mark.asyncio
async def test_donate_progress_counts_stone_amount(db):
    """The donate stage advances by the donated stone amount, then the chain
    continues with the win_pve stage (mirrors the two-stage chain_hx_01)."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "合欢宗", level_index=3, gold=2000)

    success, msg = await mgr.donate_to_sect("u1", 400)
    assert success, msg
    assert "【投名状】进度：400/1000" in msg

    player = await db.get_player_by_id("u1")
    assert player.get_sect_master_progress()["progress"] == 400

    success, msg = await mgr.donate_to_sect("u1", 600)
    assert success, msg
    assert "【投名状】完成" in msg
    # 真实配置 chain_hx_01 还有第二阶段【见血】，donate 结算后推进而非全部完成
    assert "师承任务已全部完成" not in msg
    assert "下一阶段：【见血】" in msg
    player = await db.get_player_by_id("u1")
    # 捐献贡献（400+600）+ 阶段奖励 80
    assert player.sect_contribution == 1080
    assert player.experience == 500
    assert player.get_sect_master_progress() == {
        "chain_id": "chain_hx_01",
        "stage_index": 1,
        "progress": 0,
        "done": False,
    }

    # 第二阶段【见血】：win_pve ×5 结算后全链完成
    for i in range(1, 5):
        msg = await mgr.advance_master_progress("u1", "win_pve")
        assert f"【见血】进度：{i}/5" in msg
    msg = await mgr.advance_master_progress("u1", "win_pve")
    assert "【见血】完成" in msg
    assert "宗门贡献 +120" in msg
    assert "领悟宗门功法【蚀心魔音】" in msg
    assert "师承任务已全部完成" in msg

    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == 1200
    assert player.get_sect_master_progress()["done"] is True
    skills = await db.ext.get_learned_skills("u1")
    assert len(skills) == 1
    assert skills[0]["skill_id"] == "hx_001"
    assert skills[0]["origin_sect_id"] == "huanxi"
    assert skills[0]["sect_bound"] is True

    # 查看指令显示全部完成
    success, msg = await mgr.get_master_task_status("u1")
    assert success
    assert "已全部完成" in msg


# ===== 5.3 功法领悟奖励 =====


@pytest.mark.asyncio
async def test_skill_learn_chance_grants_sect_skill(db):
    """skill_learn_chance draws a pool skill with sect attribution."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=1)

    # 直接定位到第二阶段（采药历练）
    player = await db.get_player_by_id("u1")
    player.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 1, "progress": 0, "done": False}
    )
    await db.update_player(player)

    msg = await mgr.advance_master_progress("u1", "adventure_complete")
    assert "领悟宗门功法【青云剑诀】" in msg

    skills = await db.ext.get_learned_skills("u1")
    assert len(skills) == 1
    assert skills[0]["skill_id"] == "qy_001"
    assert skills[0]["origin_sect_id"] == "qingyun"
    assert skills[0]["sect_bound"] is True
    assert skills[0]["star_level"] == 1

    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == 80


@pytest.mark.asyncio
async def test_skill_learn_chance_star_up_and_max_star_compensation(db):
    """Duplicate draws star up; max-star duplicates convert to exp."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=1)

    async def _settle_skill_stage():
        player = await db.get_player_by_id("u1")
        player.set_sect_master_progress(
            {"chain_id": "chain_qy_01", "stage_index": 1, "progress": 0, "done": False}
        )
        await db.update_player(player)
        return await mgr.advance_master_progress("u1", "adventure_complete")

    # 首次领悟
    msg = await _settle_skill_stage()
    assert "领悟宗门功法" in msg
    # 第二次：升星
    msg = await _settle_skill_stage()
    assert "升至 2 星" in msg
    # 第三次：满星（max_star=3）
    msg = await _settle_skill_stage()
    assert "升至 3 星" in msg

    player = await db.get_player_by_id("u1")
    exp_before = player.experience

    # 第四次：满星折算修为（1000 * 0.5 = 500）
    msg = await _settle_skill_stage()
    assert "已达3星圆满" in msg
    assert "折算修为 +500" in msg

    player = await db.get_player_by_id("u1")
    assert player.experience == exp_before + 500
    skills = await db.ext.get_learned_skills("u1")
    assert skills[0]["star_level"] == 3
    # 满星折算不覆盖原有归属标记
    assert skills[0]["origin_sect_id"] == "qingyun"
    assert skills[0]["sect_bound"] is True


@pytest.mark.asyncio
async def test_skill_grant_failure_keeps_stage_unsettled_and_retryable(
    db, monkeypatch
):
    """M7: when the skill grant fails, the stage is NOT settled — no
    contribution/exp is granted, stored progress is kept, and the next
    matching event retries the settlement."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=1)

    # 定位到第二阶段（采药历练，count=1，奖励含 skill_learn_chance）
    player = await db.get_player_by_id("u1")
    player.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 1, "progress": 0, "done": False}
    )
    await db.update_player(player)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated skill write failure")

    monkeypatch.setattr(db.ext, "learn_or_star_up", _boom)

    msg = await mgr.advance_master_progress("u1", "adventure_complete")
    assert msg is not None
    assert "发放失败" in msg

    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == 0  # 奖励未发
    assert player.experience == 0
    # 阶段未标记完成，进度保持，可重试
    assert player.get_sect_master_progress() == {
        "chain_id": "chain_qy_01",
        "stage_index": 1,
        "progress": 0,
        "done": False,
    }

    # 故障恢复后，下次事件重试结算成功
    monkeypatch.undo()
    msg = await mgr.advance_master_progress("u1", "adventure_complete")
    assert "【采药历练】完成" in msg
    assert "领悟宗门功法【青云剑诀】" in msg
    player = await db.get_player_by_id("u1")
    assert player.sect_contribution == 80
    skills = await db.ext.get_learned_skills("u1")
    assert len(skills) == 1 and skills[0]["skill_id"] == "qy_001"


@pytest.mark.asyncio
async def test_max_star_compensation_not_overwritten_by_stage_settlement(db):
    """M7: stage settlement after a max-star duplicate draw keeps the atomic
    exp compensation granted by learn_or_star_up (player is re-read first)."""
    mgr = SectManager(db, FakeConfigManager())
    await mgr.ensure_system_sects()
    await _join(db, mgr, "u1", "青云门", level_index=1)

    # 已满星（max_star=3）
    for _ in range(3):
        await db.ext.learn_or_star_up("u1", "qy_001", "test")

    player = await db.get_player_by_id("u1")
    player.set_sect_master_progress(
        {"chain_id": "chain_qy_01", "stage_index": 1, "progress": 0, "done": False}
    )
    await db.update_player(player)

    msg = await mgr.advance_master_progress("u1", "adventure_complete")
    assert "已达3星圆满" in msg
    assert "折算修为 +500" in msg

    player = await db.get_player_by_id("u1")
    assert player.experience == 500  # 折算修为未被整行 update 覆盖
    assert player.sect_contribution == 80
    assert player.get_sect_master_progress()["done"] is False  # 推进到第三阶段
