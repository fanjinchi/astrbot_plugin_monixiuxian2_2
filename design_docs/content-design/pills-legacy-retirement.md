# 旧九品丹药体系退役说明（2026-09-16）

## 背景

`config/items.json` 自 first commit（上游原版 `067d391`）起承载 33 个 `type=丹药` 条目（九品天梯 ×3 + 大力丸/清心丹/解毒丹/辟谷丹/焚天逆命增益丹），schema 为旧版 `effect.add_hp/add_experience` + `shop_weight`。现行丹药系统为 `pills.json`（境界突破丹）/ `exp_pills.json`（修为丹）/ `utility_pills.json`（功能丹）三表，键体系完全不同。

旧条目从未接入现行系统：商店购买拒收 `type=丹药`（回滚）、无名域注册；仅 `managers/rift_manager.py` 的秘境丹药掉落表（`RIFT_PILL_DROP_TABLE`）硬编码引用其中 5 个增益丹名。10e（`ConfigManager.get_pill_config` 合并查找）后这 5 个名字经 items 兜底可解析、`use_pill` 会**消耗但零效果**（`_use_instant_pill` 读 `hp_restore` 系键，items 条目是 `effect.*` 键）——成为活缺陷。

## 处置（hygiene-cleanup-batch 追加批次 5.x，用户已确认）

1. **删除** items.json 全部 33 个丹药条目（含血煞丹 items 侧冗余——现行解析走 utility 表）。
2. **移除** `rift_manager.py` 整套秘境丹药掉落机制（`RIFT_PILL_DROP_TABLE` / `RIFT_PILL_DROP_CHANCE` / `_roll_pill_drops` / 调用点）——掉落的本来就是不可用丹药。
3. **`get_pill_config` 删除 items 兜底分支**：「丹药 = 三表名域」成为结构保证，items 表不再承载丹药类型。
4. 测试断言②恢复为「items 零丹药条目」；断言③（表内无重名）曾保持 xfail 等 bd `-czl`（混元血容丹双 tier 共名）——2026-09-29 用户确认内容重设计未启动，直接删除被覆盖的皇品条目（util_128，保留生效中的混元先天条目 util_142），xfail 已移除转绿，bd `-czl` 关闭。

## 对丹药内容管线的约束

- **丹药一律进三表**（pills/exp/utility），禁止在 items.json 新增 `type=丹药` 条目（`tests/test_config_manager.py::test_items_carry_no_pill_entries` 是闸门）。
- 秘境丹药掉落**待重做**：`RiftManager` 掉落机制已移除，未来丹药内容设计时按三表名域重建掉落表（含品级-秘境等级匹配）。
- 增益丹（战斗 buff 类）在现行三表中**不存在品类**——如内容设计需要，先在 utility 表立品类再登记canon。
- 旧 schema（`effect.add_hp/add_experience`）不再使用；`adventure_config.json` 中毒无涯剧情的「解毒丹」是纯叙事文案，非物品引用，不受影响。
