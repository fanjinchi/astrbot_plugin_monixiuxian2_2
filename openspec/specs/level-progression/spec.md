# level-progression Specification

## Purpose

等级与境界进程：境界配置结构、等级到境界名称映射、经验曲线公式、突破成功率与失败惩罚、双修定额收益、level_index 语义。

## Requirements

### Requirement: 境界配置结构

境界配置 SHALL 仅包含：大境界名称列表 `realms`、最高等级、经验曲线参数、按大境界的突破成功率表、失败惩罚比例；MUST NOT 再逐級配置 `exp_needed`、`success_rate` 或 `base_damage/base_agility/base_speed/base_hp` 字段。最高等级 SHALL 由大境界数量推导（每大境界 10 级，末境界 9 阶，10 大境界 = 99 级封顶）。灵修与体修 SHALL 使用同构配置（`level_config.json` 与 `body_level_config.json`），两者大境界数量 MUST 一致。

#### Scenario: 配置不再包含逐級字段

- **WHEN** 系统加载 level_config.json
- **THEN** 配置中不存在任何逐級的 exp_needed/success_rate/base_* 字段，仅有大境界名称列表与公式参数

#### Scenario: 最高等级由境界数推导

- **WHEN** realms 配置为 10 个大境界
- **THEN** 最高等级为 99，99 级玩家触发突破时收到「已达到最高境界」提示

### Requirement: 等级到境界名称映射

系统 SHALL 提供统一的境界名计算入口 `get_level_name(level_index)`，全部展示场景 MUST 通过该入口，MUST NOT 再直接索引境界数据列表取 `level_name`。命名规则：等级数字的十位为大境界、个位为小阶（1-9 为「X一阶」~「X九阶」）；每个大境界的第 10 级 SHALL 命名为「下一境界初期」（如 level 10 = 筑基初期、level 20 = 金丹初期）；越界等级返回 `境界{level_index}` 兜底。

#### Scenario: 常规境界名

- **WHEN** 展示 level 15 玩家的境界
- **THEN** 显示「筑基五阶」

#### Scenario: 下一境界初期惯例

- **WHEN** 展示 level 40 玩家的境界
- **THEN** 显示「化神初期」

#### Scenario: 越界兜底

- **WHEN** 因配置错误请求超过最高等级的境界名
- **THEN** 返回「境界{level_index}」而非抛出异常

### Requirement: 经验曲线公式化

升级所需修为 SHALL 由分段幂律公式计算，不再逐級配置：

- `E(L) = early_a · L^early_exp`（L ≤ 10）
- `E(L) = pivot10 · (L/10)`（10 < L ≤ mid_end_level，pivot10 为 L=10 处衔接值）
- `E(L) = pivot50 · (L/mid_end_level)^late_exp`（L > mid_end_level，pivot50 为 L=mid_end_level 处衔接值）

全部公式参数（early_a、early_exp、mid_end_level、late_exp）SHALL 写入 config 可调，修改后重启生效。校准目标：早期每级约半天、中期 1~2 天、后期 3~7 天。

#### Scenario: 突破所需修为来自公式

- **WHEN** 练气一阶（level 1）玩家查看突破条件
- **THEN** 所需修为为公式计算的 E(1)（默认参数下 1800），而非配置表中的手写值

#### Scenario: 调整曲线无需改代码

- **WHEN** 运营将 config 中 early_a 从 1800 改为 2400 并重启
- **THEN** 全等级突破所需修为按新参数重新计算，无需修改代码

### Requirement: 突破成功率按大境界配置

突破成功率 SHALL 按目标等级所在大境界查表（默认：练气 100%、筑基 80%、金丹 65%、元婴 55%、化神 50%、炼虚 45%、合体及以后 40% 地板），MUST NOT 再逐級配置成功率。连败保底机制（每败 +5%、19 连败必成）SHALL 保持不变。

#### Scenario: 后期成功率不低于地板

- **WHEN** 地仙境界玩家突破
- **THEN** 基础成功率为 40%（不含丹药与连败加成）

### Requirement: 突破失败惩罚按本级需求比例

突破失败未死亡时，修为惩罚 SHALL 为「本级需求经验 E(L) × failure_penalty_rate」（默认 25%，config 可调），MUST NOT 再按玩家累计总修为的比例扣除。

#### Scenario: 高等级失败惩罚可控

- **WHEN** level 90 玩家突破失败且未死亡
- **THEN** 扣除修为 = E(90) × 25%，与其累计总修为无关

### Requirement: 突破死亡率下调

突破失败死亡概率区间 SHALL 由 `[0.01, 0.1]` 下调至 `[0.005, 0.03]`（config 可调），与更高的基础成功率配套降低挫败感。

#### Scenario: 死亡率在新区间内

- **WHEN** 突破失败触发死亡判定
- **THEN** 死亡概率取自 [0.005, 0.03] 区间（乘以死亡倍率后仍裁剪到 [0,1]）

### Requirement: 双修定额化收益

双修收益 SHALL 为定额：「K 小时闭关等效修为 × 境界系数 f(t)」（K 默认 2，f(t) 默认 = 大境界序号 t，均可 config 调整），MUST NOT 再按对方累计总修为的比例结算。冷却时间保持不变。

#### Scenario: 高修玩家互刷不再膨胀

- **WHEN** 两名高等级玩家互相双修
- **THEN** 双方各获得自身大境界对应的定额修为，与对方累计总修为无关

### Requirement: level_index 语义统一

玩家 `level_index` SHALL 统一为 1-based 等级数字（1 = 练气一阶，99 = 地仙九阶封顶）。所有按等级取境界名、经验、成功率的代码 MUST 使用统一入口计算，MUST NOT 将 `level_index` 当作 0-based 数组下标使用。物品/丹药/储物戒的 `required_level_index` SHALL 定义为「1-based 等级数字，0 = 无门槛」。

#### Scenario: 突破面板显示正确境界

- **WHEN** 练气一阶（level_index 1）玩家查看突破面板
- **THEN** 显示「当前境界：练气一阶、突破至：练气二阶」，所需修为为 E(1)

#### Scenario: GM 按名称设置境界

- **WHEN** GM 执行「设置境界 筑基一阶」
- **THEN** 目标玩家 level_index 被设为 11（筑基一阶），状态面板显示筑基一阶

#### Scenario: 满级判定

- **WHEN** level 99 玩家尝试突破
- **THEN** 系统提示已达到最高境界，不发生数组越界或错位
