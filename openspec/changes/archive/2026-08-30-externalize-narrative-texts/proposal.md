# Proposal: externalize-narrative-texts

## Why

叙事内容管线（`narrative-content-pipeline`）与第一季剧情大纲（`season-1-outline.md`）已就绪，但大纲梯队 1 的填充对象——突破/战斗/修炼结算/秘境探索等**高频界面文案全部硬编码在代码里**，没有可配置载体，文案变体池无处可写。bible §1.6 文案载体清单已标明这批硬编码位置（bd `yux`）；同时 `rift_config.json` 缺 `description` 字段（bd `og9`），秘境事件变体池（`rift_manager.py:324-328`）也硬编码在代码里。不先完成文案外移工程，剧情填充只能停在纸面。

代码审查（2026-08-28）另发现三处同一桥段的传承机缘文案分散硬编码在 adventure/rift/sect 三个 manager，以及 adventure/bounty/enemy 三个 manager 的内嵌 DEFAULT fallback 与 config 文件漂移的问题，应随本工程一并收敛。

## What Changes

- **新建 `config/narrative_config.json`**：承载高频界面文案的模板与变体池，按域分节（突破/战斗/修炼结算/机缘），默认值落 `data/default_configs.py`（复用 `_load_config_with_default` 模式）。运行时行为不变——首批外移**逐字搬运现有文案**，只改载体不改内容（内容重写属梯队 1 内容任务，走 `season-1-tier1-copywriting`）。
  - 突破文案（`core/breakthrough_manager.py` 成功/失败/身死道消/保命/连败保底 + 领悟功法/机缘掉落 flavor，`core/breakthrough_fortune.py` 机缘三句）
  - 战斗说书人句式（`managers/combat_manager.py` `_resolve_attack` 全部叙事句式 + `:202-265` 战斗框架开头/胜利/平局/同归于尽收束语）
  - 修炼结算文案（`handlers/player_handler.py` 闭关开始/出关结算骨架/闭关悟道 + `core/cultivation_manager.py` 灵根体质评价大表 ~48 条外移至条目型配置）
- **`rift_config.json` 增加 `description` 字段**（bd `og9`）：每秘境入口描述 + 结算叙事位；`rift_manager.py:324-328` 硬编码探索事件变体池一并外移进 rift 配置；模型/manager/UI 全链路支持。
- **历练事件文案载体**（bd `tyt` 工程侧并入）：`adventure_config.json` 事件条目增加题材标签位 `tags` 与按境界段分桶的文案变体池 `desc_variants`；运行时按玩家境界段从当前段桶+通用桶随机取文案，空桶回落现有 `desc`（逐字保留为兜底）。事件数值字段（`exp_mult`/`gold_mult` 等）不动；题材文案撰写与结构补量属内容任务，不在本变更。
- **传承之地文案收敛**：`adventure_manager.py` / `rift_manager.py` 两处"偶遇传承之地"近似重复 + `sect_manager.py` 领取制（"需先战胜守护者"）同主题文案，收敛为 `narrative_config.json` 单一模板簇（偶遇/领取两个场景各一模板）。
- **fallback 收敛**：adventure/bounty/enemy 三 manager 的内嵌 DEFAULT 副本改为从 `data/default_configs.py` 单源引用（或删除内嵌副本），消除文案双份漂移。
- **删除死代码** `utils/config_loader.py`（`ConfigLoader` 全项目无调用）。
- 模板插值变量契约校验：加载时校验模板引用的变量集合 ⊆ 代码提供的变量集合，断裂即启动报错（防文案侧写了代码不提供的变量）。

**明确不在本变更内**：
- 任何文案内容本身的撰写/改写（梯队 1 内容任务，`season-1-tier1-copywriting`，依赖本变更的载体）
- 历练事件的题材文案撰写与结构补量（bd `tyt` 内容侧：弹药库挂载、disaster 组扩量、四宗专属组补齐）——走 design_docs 管线，由 `season-1-tier1-copywriting` 及后续内容任务填充
- Boss 名号池迁移、灵眼/银行广播文案外移（P2/P3，后续变更）
- 数值说明类文本（突破成功率分解 `rate_info`、结算数值行、属性面板说明行）不外移——保持简洁直白、留在代码原位（world-bible §1.3 注，2026-08-28 定）

## Capabilities

### New Capabilities

- `narrative-text-config`: 叙事文案配置化载体——高频界面文案（突破/战斗/修炼结算/机缘/传承偶遇/秘境）以模板与变体池形式存于 config，运行时从 config 读取并渲染；模板插值变量契约的机器校验；`rift_config.json` 的 description 与探索事件池字段；`adventure_config.json` 事件条目的题材标签位与按境界段分桶的文案变体池。

### Modified Capabilities

（无——不改变任何外部可观察行为的语义，仅迁移文案载体；战斗/突破/结算的数值与流程逻辑不变。）

## Impact

- **代码**：`core/breakthrough_manager.py`、`core/breakthrough_fortune.py`、`core/cultivation_manager.py`、`managers/combat_manager.py`、`managers/rift_manager.py`、`managers/adventure_manager.py`、`managers/sect_manager.py`、`managers/bounty_manager.py`、`managers/enemy_manager.py`、`handlers/player_handler.py`、`config_manager.py`、`data/default_configs.py`；删除 `utils/config_loader.py`
- **配置**：新建 `config/narrative_config.json`；`config/rift_config.json` 加 `description`（及探索事件池字段）；`config/adventure_config.json` 事件条目加可选 `tags`/`desc_variants`
- **测试**：`tests/` 新增载体加载/模板变量契约/rift description 渲染的用例；既有战斗/突破测试保持绿
- **流程**：本变更是纯工程变更（AGENTS.md §15 例外条款），不含内容填充；落地后解锁 bd `bk4`/`lky`/`u4h` 的内容任务与 `season-1-tier1-copywriting` 的导入步骤
- **bd**：落地后关闭 `yux`、`og9`；更新 `tyt`（工程侧随本变更落地，内容侧保留待 design_docs 管线）
