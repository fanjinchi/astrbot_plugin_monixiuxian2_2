# Tasks: 等级配置与经验曲线公式化

## 1. 配置重构

- [ ] 1.1 重写 `config/level_config.json` 为新结构：`realms` 大境界名列表（练气…地仙）、`exp_curve` 参数（early_a=1800, early_exp=1.5, mid_end_level=50, late_exp=1.7）、`success_rates` 表（1.0/0.8/0.65/0.55/0.5/0.45/0.4×4）、`failure_penalty_rate=0.25`
- [ ] 1.2 重写 `config/body_level_config.json` 为同构结构（体修境界名列表从旧配置提取，大境界数量与灵修一致）
- [ ] 1.3 `config/game_config.json` 新增：`boss.enabled`、`pve.enabled`（默认 true）；`dual_cultivation` 节新增定额参数（K=2 小时、realm_factor 模式）
- [ ] 1.4 `_conf_schema.json` 中 `BREAKTHROUGH_DEATH_PROBABILITY` 默认值由 `[0.01, 0.1]` 改为 `[0.005, 0.03]`

## 2. ConfigManager 中央 API

- [ ] 2.1 实现新结构加载与校验（灵修/体修 realms 长度一致性告警），移除对旧逐級列表的依赖
- [ ] 2.2 实现 `get_level_name(level_index, cultivation_type)`：十位大境界/个位小阶计算，stage 10 命名「下一境界初期」，越界兜底 `境界{n}`
- [ ] 2.3 实现 `get_exp_needed(level_index)`：分段幂律公式（L≤10 幂律段 / ≤50 线性衔接 / >50 幂律放大）
- [ ] 2.4 实现 `get_success_rate(level_index)`（按目标级大境界查表）、`get_max_level(cultivation_type)`（realms×10−1）、`get_level_index_by_name(name)`（名称→等级反查表，含「初期」名）

## 3. 突破系统改造

- [ ] 3.1 `core/breakthrough_manager.py`：突破条件、成功率、境界名显示全部改走中央 API；满级判定改 `level_index >= get_max_level()`；失败惩罚改 `E(L) × failure_penalty_rate`（替换累计总修为 10%）
- [ ] 3.2 `handlers/breakthrough_handler.py`：突破面板改走中央 API（当前/目标境界名、所需修为、基础成功率、破境丹 target_level 提示）
- [ ] 3.3 `models.py`：`get_level()` / `get_required_exp()` 改为调用中央 API，删除按 `level` 字段遍历匹配的旧实现

## 4. level_name 消费点收敛（纯显示替换）

- [ ] 4.1 `core/pill_manager.py`、`handlers/pill_handler.py`：丹药境界需求提示改 `get_level_name()`
- [ ] 4.2 `core/equipment_manager.py`、`core/storage_ring_manager.py`、`core/shop_manager.py`：装备/储物戒/商店境界需求提示改 `get_level_name()`（required_level_index 数值比较不动，语义固定为 1-based、0=无门槛）
- [ ] 4.3 `managers/rift_manager.py`：删除自带的 `_get_level_name` 与内置境界名兜底列表，改调中央 API

## 5. off-by-one 修复

- [ ] 5.1 `handlers/player_handler.py:332`：闭关上限大境界加成 `(level_index // 9)` 改 `((level_index - 1) // 10)`
- [ ] 5.2 `core/gm_manager.py`：设置境界改用 `get_level_index_by_name()` 反查，替换 0-based enumerate；错误提示列出可用境界名
- [ ] 5.3 `managers/impart_manager.py`：`_max_level_index()` 改调 `get_max_level()`

## 6. 双修定额化

- [ ] 6.1 `managers/dual_cultivation_manager.py`：收益改为「K 小时 × BASE_EXP_PER_MINUTE × 60 × 灵根倍率 × f(t)」，读取 game_config 参数，删除按对方累计总修为 10% 的结算；提示文案同步更新

## 7. Boss/PvE 功能开关

- [ ] 7.1 `main.py`：`boss.enabled=false` 时不启动 `_schedule_boss_spawn` 任务；Boss 指令（世界Boss/挑战Boss/生成Boss）入口按开关门控，回复玩法维护提示
- [ ] 7.2 `handlers/` 秘境等 PvE 战斗入口按 `pve.enabled` 门控；确认历练（adventure）不受开关影响
- [ ] 7.3 `managers/boss_manager.py`：`_get_level_base` 等 `base_*` 读取点加防御（开关关闭时不触达；触达时告警而非崩溃）

## 8. 测试

- [ ] 8.1 新增 ConfigManager 中央 API 单测：境界名（含 stage 10「下一境界初期」、越界兜底）、E(L) 公式三段衔接连续性、成功率表、max_level、名称反查
- [ ] 8.2 新增/更新突破测试：1-based 语义下突破面板显示、满级 99 判定、失败惩罚 = E(L)×25%
- [ ] 8.3 更新受影响的既有测试（level_config 结构变更的 fixture、GM 设置境界、双修收益）
- [ ] 8.4 新增开关测试：boss.enabled/pve.enabled=false 时指令门控与定时任务不启动

## 9. 文档与版本

- [ ] 9.1 `metadata.yaml` 版本号递增
- [ ] 9.2 `README.md` 更新日志追加本次变更
- [ ] 9.3 `handlers/misc_handler.py` 的「修仙帮助」文本同步（双修定额化、Boss/PvE 维护开关说明）

## 10. 验证

- [ ] 10.1 `uv run ruff format . && uv run ruff check .` 通过
- [ ] 10.2 `timeout 120 uv run python -m pytest tests/ -q` 全绿
- [ ] 10.3 复跑 `design_docs/level-exp-curve/sim_exp_curve.py` 确认节奏参数与实现一致
- [ ] 10.4 `openspec validate adjust-level-exp-curve` 通过
