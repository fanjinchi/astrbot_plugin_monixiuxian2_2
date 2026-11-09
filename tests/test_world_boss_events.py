"""Child D 世界 Boss 提交后事件验收测试（R7 / AC6）。

- renderer 只读出生快照的五个文案键 + narrative_approved，禁读 narrative_config
  与代码 fallback：未批准/缺键/空文案一律返回 None（禁播）；
- dispatcher 先按发送时目标快照展开唯一 (event_id, platform, group_id) delivery，
  再逐条条件 claim，网络 await 全程在 DB 事务外；
- 已知失败按退避重试、耗尽后转 uncertain；发送结果不确定立即 uncertain 且
  永不自动重试；已 sent 的目标不因其他目标失败重播；
- 已提交但没有 delivery 的事件由固定 10 分钟窗口的恢复扫描幂等补展开。
"""

import pytest
import pytest_asyncio

from tests.helpers import load_package_module

pytestmark = pytest.mark.asyncio

_repo_mod = load_package_module(
    "data/pve_repository.py", "astrbot_plugin_monixiuxian2_2.data.pve_repository"
)
_events_mod = load_package_module(
    "managers/world_boss_events.py",
    "astrbot_plugin_monixiuxian2_2.managers.world_boss_events",
)
_migration_mod = load_package_module(
    "data/migration.py", "astrbot_plugin_monixiuxian2_2.data.migration"
)
from tests.test_player_health_foundation import T0, StubConfigManager  # noqa: E402

OutboxRepository = _repo_mod.OutboxRepository
WorldBossRepository = _repo_mod.WorldBossRepository
WorldBossEventDispatcher = _events_mod.WorldBossEventDispatcher
DeliveryUncertain = _events_mod.DeliveryUncertain
render_event_text = _events_mod.render_event_text
import sys  # noqa: E402

DataBase = sys.modules["astrbot_plugin_monixiuxian2_2.data"].DataBase

INSTANCE_ID = "wb_wb_lq_ba_1700000000"
TEXTS = {
    "spawn_text": "黑风峡方向煞气冲天——裂峡罴王出峡了！",
    "phase2_text": "罴王吃痛狂性大发，掌势更猛了！",
    "phase3_text": "罴王遍体鳞伤步履踉跄，甲皮都松动了。",
    "kill_text": "罴王轰然倒地，峡谷回音久久不散。",
    "dissipate_text": "罴王拖着伤躯退回黑风峡深处，只留下满地狼藉。",
}


@pytest_asyncio.fixture
async def db():
    database = DataBase(":memory:")
    await database.connect()
    await _migration_mod.MigrationManager(
        database.conn, StubConfigManager()
    ).migrate_or_reset()
    yield database
    await database.close()


async def _insert_instance(
    db,
    *,
    instance_id: str = INSTANCE_ID,
    approved: bool = True,
    texts: dict | None = None,
    raw_snapshot=None,
    now: int = T0,
):
    snapshot = dict(TEXTS)
    snapshot["narrative_approved"] = approved
    if texts is not None:
        snapshot.update(texts)
    repo = WorldBossRepository(db.conn)
    row, _ = await repo.insert_instance(
        instance_id=instance_id,
        profile_id="wb_lq_ba",
        profile_version=1,
        max_hp=1000,
        now=now,
        expires_at=now + 48 * 3600,
        boss_name="裂峡罴王",
        boss_level=1,
        atk=18,
        defense=0,
        agility=8,
        speed=11,
        armor_value=7,
        birth_snapshot=raw_snapshot if raw_snapshot is not None else snapshot,
    )
    return row


async def _append_event(
    db,
    *,
    event_type: str = _events_mod.EVENT_SPAWN,
    aggregate_id: str = INSTANCE_ID,
    aggregate_type: str = _events_mod.AGGREGATE_TYPE,
    payload: dict | None = None,
    occurred_at: int = T0,
    business_key: str | None = None,
):
    outbox = OutboxRepository(db.conn)
    key = business_key or f"world_boss:test:{event_type}:{aggregate_id}:{occurred_at}"
    row, _ = await outbox.append_event(
        event_id=f"evt:{key}",
        business_key=key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        occurred_at=occurred_at,
        payload=payload if payload is not None else {"copy_key": "spawn_text"},
    )
    return row


class RecordingSender:
    """记录发送内容；可按平台注入已知失败或不确定结果。"""

    def __init__(self) -> None:
        self.calls = []
        self.failures = {}
        self.uncertain = set()

    async def __call__(self, platform: str, group_id: str, text: str) -> None:
        self.calls.append((platform, group_id, text))
        if platform in self.uncertain:
            raise DeliveryUncertain("timeout after write")
        if platform in self.failures:
            raise RuntimeError(self.failures[platform])


def make_dispatcher(db, sender, targets, *, clock=None, **kwargs):
    return WorldBossEventDispatcher(
        db,
        sender=sender,
        targets=targets,
        clock=clock if clock is not None else (lambda: T0),
        **kwargs,
    )


async def _deliveries(db, event_id):
    return await OutboxRepository(db.conn).list_deliveries_for_event(event_id)


# ─────────────────────────────── renderer ─────────────────────────────────


async def test_renderer_reads_approved_snapshot_text(db):
    instance = await _insert_instance(db)
    event = await _append_event(db)

    assert render_event_text(event, instance) == TEXTS["spawn_text"]


async def test_renderer_refuses_unapproved_or_missing_copy(db):
    event = await _append_event(db)
    unapproved = await _insert_instance(db, instance_id="wb_a", approved=False)
    assert render_event_text(event, unapproved) is None

    empty = await _insert_instance(db, instance_id="wb_b", texts={"spawn_text": "   "})
    assert render_event_text(event, empty) is None

    missing_key = await _append_event(
        db,
        business_key="bk-missing",
        payload={"copy_key": "not_a_copy_key"},
    )
    approved = await _insert_instance(db, instance_id="wb_c")
    assert render_event_text(missing_key, approved) is None


async def test_renderer_ignores_foreign_events_and_broken_snapshots(db):
    instance = await _insert_instance(db, raw_snapshot="{broken json")
    event = await _append_event(db)
    assert render_event_text(event, instance) is None

    good_instance = await _insert_instance(db, instance_id="wb_good")
    foreign = await _append_event(
        db, business_key="bk-foreign", event_type="adventure_resolved"
    )
    assert render_event_text(foreign, good_instance) is None
    wrong_aggregate = await _append_event(
        db, business_key="bk-agg", aggregate_type="adventure_settlement"
    )
    assert render_event_text(wrong_aggregate, good_instance) is None


async def test_copy_key_mapping_covers_all_five_texts():
    assert _events_mod.COPY_KEY_BY_PHASE == {2: "phase2_text", 3: "phase3_text"}
    assert _events_mod.EVENT_TYPES == {
        "world_boss_spawn",
        "world_boss_stage",
        "world_boss_defeated",
        "world_boss_dissipated",
    }


# ────────────────────────────── dispatcher ────────────────────────────────


async def test_expand_creates_one_delivery_per_destination_idempotently(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1"), ("aiocqhttp", "g2")])

    assert await dispatcher.expand(event["event_id"]) == 2
    assert await dispatcher.expand(event["event_id"]) == 0

    deliveries = await _deliveries(db, event["event_id"])
    assert {(d["platform"], d["group_id"]) for d in deliveries} == {
        ("aiocqhttp", "g1"),
        ("aiocqhttp", "g2"),
    }
    assert all(d["state"] == "queued" for d in deliveries)


async def test_dispatch_sends_and_marks_delivery_sent(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])

    summary = await dispatcher.dispatch_pending()

    assert summary == {"expanded": 1, "sent": 1, "retried": 0, "uncertain": 0}
    assert sender.calls == [("aiocqhttp", "g1", TEXTS["spawn_text"])]
    deliveries = await _deliveries(db, event["event_id"])
    assert deliveries[0]["state"] == "sent"
    assert deliveries[0]["claim_owner"] == ""


async def test_recovery_scan_expands_events_without_deliveries(db):
    await _insert_instance(db, now=T0)
    event = await _append_event(db, occurred_at=T0)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])

    summary = await dispatcher.dispatch_pending(now=T0 + 60)

    assert summary["expanded"] == 1
    assert summary["sent"] == 1
    assert len(sender.calls) == 1
    assert len(await _deliveries(db, event["event_id"])) == 1


async def test_recovery_scan_ignores_events_older_than_window(db):
    await _insert_instance(db, now=T0)
    event = await _append_event(db, occurred_at=T0)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])

    summary = await dispatcher.dispatch_pending(now=T0 + 601)

    assert summary["expanded"] == 0
    assert sender.calls == []
    assert await _deliveries(db, event["event_id"]) == []


async def test_partial_success_never_replays_sent_destination(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    sender.failures["broken"] = "network down"
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1"), ("broken", "g2")])

    summary = await dispatcher.dispatch_pending()

    assert summary == {"expanded": 2, "sent": 1, "retried": 1, "uncertain": 0}
    deliveries = {d["platform"]: d for d in await _deliveries(db, event["event_id"])}
    assert deliveries["aiocqhttp"]["state"] == "sent"
    assert deliveries["broken"]["state"] == "queued"
    assert deliveries["broken"]["next_retry_at"] == T0 + 60

    # 第二次轮询只重发失败目标，已 sent 的不再发送（故障已恢复）。
    sender.failures.pop("broken")
    summary = await dispatcher.dispatch_pending(now=T0 + 120)
    assert summary["sent"] == 1
    # aiocqhttp 只发送一次；broken 首轮失败一次、恢复后重试成功一次。
    assert [call[0] for call in sender.calls] == ["aiocqhttp", "broken", "broken"]


async def test_known_failure_retries_then_becomes_uncertain(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    sender.failures["broken"] = "network down"
    dispatcher = make_dispatcher(db, sender, [("broken", "g1")], max_attempts=2)

    first = await dispatcher.dispatch_pending()
    assert first["retried"] == 1
    second = await dispatcher.dispatch_pending(now=T0 + 600)
    assert second["uncertain"] == 1

    deliveries = await _deliveries(db, event["event_id"])
    assert deliveries[0]["state"] == "uncertain"
    assert not (await dispatcher.dispatch_pending(now=T0 + 1200))["sent"]


async def test_uncertain_send_is_never_auto_retried(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    sender.uncertain.add("aiocqhttp")
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])

    summary = await dispatcher.dispatch_pending()
    assert summary["uncertain"] == 1
    deliveries = await _deliveries(db, event["event_id"])
    assert deliveries[0]["state"] == "uncertain"

    await dispatcher.dispatch_pending(now=T0 + 3600)
    assert len(sender.calls) == 1


async def test_unapproved_narrative_is_parked_without_sending(db):
    await _insert_instance(db, approved=False)
    event = await _append_event(db)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])

    summary = await dispatcher.dispatch_pending()

    assert summary["uncertain"] == 1
    assert sender.calls == []
    deliveries = await _deliveries(db, event["event_id"])
    assert deliveries[0]["state"] == "uncertain"
    assert "未批准" in deliveries[0]["last_error"]


async def test_delivery_requires_live_claim_before_send(db):
    await _insert_instance(db)
    event = await _append_event(db)
    sender = RecordingSender()
    dispatcher = make_dispatcher(db, sender, [("aiocqhttp", "g1")])
    await dispatcher.expand(event["event_id"])

    outbox = OutboxRepository(db.conn)
    claimed = await outbox.claim_delivery(
        (await _deliveries(db, event["event_id"]))[0]["delivery_id"],
        owner="someone-else",
        lease_until=T0 + 600,
        now=T0,
    )
    assert claimed is not None

    # 已被别人 claim 的 delivery 本轮不再发送。
    summary = await dispatcher.dispatch_pending()
    assert summary["sent"] == 0
    assert sender.calls == []
    assert (await _deliveries(db, event["event_id"]))[0][
        "claim_owner"
    ] == "someone-else"
    # 陈旧 dispatching 由管理面暴露，不自动回收（prd R7）。
    stale = await outbox.list_stale_dispatching(now=T0 + 601)
    assert len(stale) == 1
