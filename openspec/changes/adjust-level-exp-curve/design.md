# Design: 等级配置与经验曲线公式化

## Context

当前 `level_config.json` 对 99 级逐一手写 `exp_needed`/`success_rate`/`base_*`：

- **曲线崩塌**：元婴后 exp 封顶 600 亿、成功率 0.01%，模拟显示 36 级后每级需上万年；前期又分钟级秒升（见 `design_docs/level-exp-curve/exp-curve-report.md`）。
- **`base_*` 失去消费者**：升级属性已改突破随机成长；仅剩 boss_manager（将随开关关闭）与历史迁移脚本引用。
- **level_index 语义混乱（本次排查新发现）**：玩家 `level_index` 为 **1-based**（`level_index=1`=练气一阶，测试已锁定），但约 10 处代码把它当 0-based 数组下标用 `level_data[level_index]`，存在系统性 off-by-one：
  - `core/breakthrough_manager.py`：突破所需修为读到的是「下下级」配置（练气一阶突破要求三阶的 1200 而非二阶的 500），显示境界名整体错位一阶，满级被 `>= len-1` 卡在 98 级
  - `core/gm_manager.py` 设置境界：按 0-based 下标反查，设置结果比目标低一阶
  - `handlers/player_handler.py:332`：闭关上限用 `level_index // 9` 算大境界，与「10 级一境界」不符
  - 装备/丹药/储物戒的 `required_level_index`：数值比较按 1-based 恰好正确，但显示名 `level_data[required]` 错位一阶
- **双修乘性漏洞**：双方各得对方累计总修为 10%，高修互刷日收益可达正常收入数十倍。
- **Boss/PvE 依赖 `base_*`**：boss_manager 用它生成 Boss 属性，删除字段前必须先有关闭手段。

## Goals / Non-Goals

**Goals:**

- level_config 简化为「大境界名称 + 曲线参数 + 成功率表 + 最高等级」，境界/层由等级直接计算
- 经验需求由分段幂律公式生成，参数全部 config 可调；节奏：早期 ~半天/级、中期 1~2 天/级、后期 3~7 天/级、满级约 300 天（含失败 ~380 天）
- `level_index` 语义统一为 1-based，所有境界名/经验/成功率查询收敛到 ConfigManager 中央 API，消除 off-by-one
- 失败惩罚改为本级需求 25%；成功率按大境界表（40% 地板）；死亡率下调至 [0.005, 0.03]
- 双修定额化：K=2 小时闭关等效 × 境界系数
- `boss.enabled` / `pve.enabled` 开关，关闭 Boss 生成任务、Boss 指令与秘境 PvE 战斗（历练保留）

**Non-Goals:**

- 不改数据库 schema，不迁移存量玩家数据（`experience` 语义不变）
- 不改修为丹/商店物品/灵眼等固定收益数值（原则见 `design_docs/level-exp-curve/balance-recommendations.md`，后续策划）
- 不重做 Boss/PvE 模块（仅加开关）；不设计保命道具（记占位）
- 不改战斗引擎本身

## Decisions

### D1: level_config 新结构

```json
{
  "max_level": 99,
  "realms": ["练气", "筑基", "金丹", "元婴", "化神", "炼虚", "合体", "大乘", "渡劫", "地仙"],
  "exp_curve": { "early_a": 1800, "early_exp": 1.5, "mid_end_level": 50, "late_exp": 1.7 },
  "success_rates": [1.0, 0.8, 0.65, 0.55, 0.5, 0.45, 0.4, 0.4, 0.4, 0.4],
  "failure_penalty_rate": 0.25
}
```

- `realms` 列表即最高大境界限制：`max_level = len(realms) * 10 - 1`（每境界第 10 级是下一境界初期，末境界只有 9 阶），99 级封顶。体修 `body_level_config.json` 同构（独立境界名列表）。
- 选择 JSON 对象而非逐級数组：配置即公式参数，消除手写 99 条的维护负担与不一致风险。

### D2: ConfigManager 中央 API（收敛所有直读点）

- `get_level_name(level_index, cultivation_type="灵修")` — 计算式：`stage == 10 → 下一境界名 + "初期"`，否则 `当前境界名 + 中文数字(stage) + "阶"`；越界返回 `f"境界{level_index}"`
- `get_exp_needed(level_index)` — 分段公式（见 D3），返回突破到 `level_index+1` 所需修为
- `get_success_rate(level_index)` — 按目标级所在大境界查 `success_rates`
- `get_max_level(cultivation_type)` — 由 realms 长度推导
- 替换点：`breakthrough_manager`、`breakthrough_handler`、`pill_handler`、`storage_ring_manager`、`equipment_manager`、`shop_manager`、`pill_manager`、`gm_manager`、`rift_manager`、`models.get_level/get_required_exp`、`impart_manager._max_level_index`
- 备选方案（保留 level_data 列表并修 off-by-one）被否：逐級列表正是要消除的对象，且计算式命名与公式查询天然一致

### D3: 经验曲线公式（分段幂律，参数 config 可调）

```
E(L) = early_a · L^early_exp                L ≤ 10
E(L) = pivot10 · (L/10)                     10 < L ≤ 50   （pivot10 = early_a·10^early_exp，线性衔接）
E(L) = pivot50 · (L/mid_end_level)^late_exp L > 50        （pivot50 = pivot10·5）
```

模拟校准结果：L1≈0.6h、L9≈15h（半天/级）、L30≈1.8d、L50≈2.7d、L99≈6.4d、满级累计 ~300 天。参数微调只需改 config 后重启。备选单公式（`a·t²·s²`）被否：当前 G(L) 几乎不随等级增长，单公式无法同时满足三段节奏（报告第三节）。

### D4: 突破配套数值

- **失败惩罚**：`experience -= E(L) × failure_penalty_rate`（25%），替换原「累计总修为 10%」。原机制在高等级使期望时间膨胀 10 倍（报告第四节）。
- **成功率表**：按目标级大境界查表（40% 地板），连败保底（+5%/败、19 连败必成）逻辑不变。
- **死亡率**：`BREAKTHROUGH_DEATH_PROBABILITY` `[0.01, 0.1]` → `[0.005, 0.03]`（_conf_schema VALUES 默认值）。

### D5: 双修定额化

```
双修收益 = K小时 × BASE_EXP_PER_MINUTE × 60 × 灵根倍率 × f(t)
f(t) = t（大境界序号，config 可换 t^1.5/t^2）
```

K=2 写入 `game_config.json` 的 `dual_cultivation` 节；每日理论上限 48h 闭关等效，与正常日收益同数量级。

### D6: Boss/PvE 开关

`game_config.json` 新增 `boss.enabled`（默认 true，过渡期保持现状）与 `pve.enabled`。关闭时：

- `main.py` 不启动 `_schedule_boss_spawn` 定时任务
- Boss 指令（世界Boss/挑战Boss）与秘境 PvE 入口回复「玩法维护中」
- 历练（adventure）不受影响——不依赖 `base_*`，纯收益玩法
- 开关为静态配置，重启生效；实现位置集中在 main.py 指令注册与 BossHandlers/RiftHandlers 入口

### D7: required_level_index 语义统一

物品/丹药/储物戒的 `required_level_index` 定义为「1-based 等级数字，0 = 无门槛」——现有数值比较逻辑恰好已符合，无需改配置数据；仅需把显示处改为 `get_level_name(required_level)` 修正错位一阶的提示文案。

### D8: 顺手修正的 off-by-one

- `player_handler.py` 闭关上限：`(level_index // 9)` → `((level_index - 1) // 10)`
- `gm_manager` 设置境界：ConfigManager 初始化时构建 `名称→等级` 反查表（含「初期」名），替换 0-based enumerate
- `impart_manager._max_level_index`：改用 `get_max_level()`

## Risks / Trade-offs

- [存量玩家当前等级在新曲线下修为可能远超/不足本级需求] → 突破仅比较 `experience >= E(L)`，超玩家直接可突破（爽感），不足者按新曲线补齐；不重置 experience，可接受
- [曲线参数后续调整会影响全部玩家节奏] → 参数集中 config + `sim_exp_curve.py` 可复跑校准；调整前先在模拟中验证
- [开关关闭期间 boss_config/enemies.json 的 `base_*` 依赖代码仍在仓库] → 开关保证运行时不触达；Boss/PvE 重做时按 attribute-numerics 的 PvE 基准要求重写属性生成
- [体修境界名列表与灵修不同步维护] → 两文件同构校验（长度一致），加载时告警
- [f(t) 线性可能让双修在后期偏强/偏弱] → f(t) 形式 config 可调，配合平衡建议文档第 1 节复跑校准

## Migration Plan

1. 部署顺序：先合入含开关的代码（开关默认开），再改 level_config 结构 + ConfigManager API + 各消费点，最后按运营需要关闭 boss/pve
2. 数据库无变更、无迁移版本；`data/migration.py:2074` 的历史迁移（引用旧 base_hp）保持不变——它只在老库升级路径执行，届时旧字段仍在历史配置快照语义内（迁移脚本本身有 `getattr` 防御）
3. 回滚：level_config.json 与代码同版本回退即可；无持久化状态依赖新结构
4. 验证：`uv run ruff format . && uv run ruff check .`、`timeout 120 uv run python -m pytest tests/ -q`、`design_docs/level-exp-curve/sim_exp_curve.py` 复跑确认节奏

## Open Questions

- f(t) 最终取线性还是 t^1.5？建议上线后按双修实际使用频率复跑一次模拟再定（当前默认线性）
- 体修的境界名列表内容（是否沿用现有 body_level_config 的境界名）——实现时从旧配置提取
