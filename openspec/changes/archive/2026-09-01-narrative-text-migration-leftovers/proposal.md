# Proposal: narrative-text-migration-leftovers

## Why

已归档变更 `externalize-narrative-texts`（2026-08-30 归档）为高频叙事文案建立了配置化载体，但实施时发现两个域各有一批硬编码文案不在原任务点位清单内，成为遗留尾巴（bd `astrbot_plugin_monixiuxian2_2-9ux`、`astrbot_plugin_monixiuxian2_2-ji7`）：突破域的储物戒已满机缘掉落句，以及战斗域静态效果处理器的六类句式与回合头。这些文案至今仍需改代码才能改文案，与叙事内容管线"文案可配置"的目标不一致，补齐后两域 flavor 文案的外移才算完整。

## What Changes

- **突破域补漏（bd `9ux`）**：`core/breakthrough_manager.py` `_apply_breakthrough_fortune` 中的储物戒已满机缘掉落句（现 `:538`）外移至 `narrative_config` 的 `fortune` 节（与机缘掉落三句同节，场景 key 如 `storage_full_drop`），逐字搬运、池长 1。
- **战斗域补漏（bd `ji7`）**：`managers/combat_manager.py` 以下硬编码句式外移至 `narrative_config` 的 `combat` 节，逐字搬运、池长 1：
  - 回合头 `-- 第 N 回合 --`（`resolve_combat`，现 `:255`）
  - 反击结算句（`_handler_counter`，现 `:478-481`）
  - 治疗结算句（`_handler_heal`，现 `:521-523`）
  - dot 附着句（`_handler_dot`，现 `:568-570`）
  - 叠加上限拒绝句（`_attach_stat_status`，现 `:645-648`）
  - 免死庇护授予句（`_handler_survive`，现 `:699`）
  - dot 侵蚀结算句（`_tick_status_effects`，现 `:807-809`）
- 新增场景同步登记默认值（`data/narrative_defaults/` 对应分片）与插值变量契约（`SCENE_VARS`），加载时校验沿用既有 `_validate_narrative_config` 链路。
- 运行时行为不变：只改载体不改内容，数值与流程逻辑零变更。

**明确不在本变更内**：

- 任何文案内容本身的撰写/改写（内容任务走 design_docs 管线）
- 战斗信息面板行（`combat_manager.py:238-245` 属性面板）、突破 `rate_info` 数值分解等数值说明类文本——沿用 externalize-narrative-texts design D6 结论，留在代码原位
- Boss 广播等其他域文案外移（原变更已定为后续变更范围）

## Capabilities

### New Capabilities

（无——不引入新能力，仅扩展既有能力的覆盖范围。）

### Modified Capabilities

- `narrative-text-config`: 扩展「叙事文案配置化载体」的覆盖范围——突破域机缘掉落的储物戒已满句与战斗域静态效果处理器六类句式、回合头纳入配置化载体；模板插值变量契约校验同步覆盖新增场景。

## Impact

- **代码**：`core/breakthrough_manager.py`（1 处取数点替换）、`managers/combat_manager.py`（7 处取数点替换，静态效果处理器经 `state["engine"]` 访问渲染入口）
- **配置/默认值**：`config/narrative_config.json` 的 `fortune`/`combat` 节各增场景；`data/narrative_defaults/fortune.py`、`data/narrative_defaults/combat.py` 增默认文案与 `SCENE_VARS` 契约（既有 `combat.py` 分片 docstring 中"回合头/效果处理器句式不在范围"的注记需同步修正）
- **测试**：`tests/` 新增/更新对应场景的外移核对用例；既有 `test_combat_engine.py`、`test_breakthrough_manager.py` 等保持绿（池长 1 逐字搬运，断言不变）；functional_tests 相关域回归由用户手动发起
- **全库扫描结论（2026-08-30）**：突破/战斗两域除上述 8 个点位外无其他同类漏网 flavor 硬编码；两域剩余中文文本均为数值/规则说明类（突破 `rate_info`、贷款还款、战斗属性面板行、Boss 广播等），按既有约定不外移
- **流程**：纯工程变更（AGENTS.md §15 例外条款），不含内容填充；落地后关闭 bd `9ux`、`ji7`
- **bd**：来源 issue `astrbot_plugin_monixiuxian2_2-9ux`、`astrbot_plugin_monixiuxian2_2-ji7`
