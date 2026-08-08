# design_docs — 设计资料库

本目录存放供设计（重新设计数值、战斗、技能等系统）时查阅的参考资料，供开发者与 AI 助手读取。

**类型标注**：资料清单中每项标注内容归属——

- **本项目**：基于本插件（AstrBot 修仙插件）源码、配置或运行数据产出的分析、模拟与设计，反映本项目当前设计事实；
- **外部参考**：其他游戏（My Brute、Q宠大乐斗等）或网络调研资料，仅作设计蓝本与灵感来源，**不代表本项目现状**；
- **混合**：目录内同时包含本项目产出与外部参考，通常可按文件名前缀区分（如 `xiuxian-*` / `worker-xiuxian-*` 为本项目，`mybrute-*` / `qpet-*` 为竞品）。

## 资料清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `current-design-report.md` | 本项目 | 现有系统架构与数值设计报告（基于源码静态分析，含 `file:line` 引用，数据库以 migration v27 为准）。创建于 2026-07-29、最近更新 2026-08-08（头部有文档状态标注），作为数值/战斗/技能重设计的**活基线资料**（非归档）；架构总览以 `project-architecture.md` 为准。 |
| `project-architecture.md` | 本项目 | **架构与系统功能设计总览**（2026-08-07 建立）：分层架构与关键机制、20 个子系统功能设计表（入口/核心数值/冷却）、openspec 契约摘要与滞后点、重设计里程碑时间线、进行中工作（bd）对照、资料导航与维护约定。新增/修改功能前建议先读。 |
| `mybrute/` | 外部参考 | My Brute（Motion-Twin 自动战斗页游）设计调研：wiki 资料整理 + 网络调研笔记。 |
| `qpet-daledou/` | 外部参考 | Q宠大乐斗（早期版本，约 2010-2012）设计调研笔记。 |
| `attribute-growth/` | 混合 | 属性成长与镜像战 TTK 调研：`xiuxian-*`、`worker-xiuxian-report.md` 为本插件蒙特卡洛模拟；`mybrute-*`、`qpet-*` 为竞品模拟；另含业界自动战斗游戏平衡方案网络调研（`auto-battle-balance-web-research.md`）。汇总分析入口 `attribute-growth-analysis.md`，本项目成长/加成平衡设计方案 `growth-balance-proposals.md`。 |
| `content-design/` | 本项目 | 玩家侧内容设计工作区（武器/功法/心法定稿数值，最终产出 `config/weapons.json` / `skills.json` / `heart_methods.json`）；设计蓝本取自 `mybrute/`、`qpet-daledou/` 外部调研。 |
| `level-exp-curve/` | 本项目 | 升级经验曲线蒙特卡洛模拟与平衡建议（基于本插件修炼收益假设，如 `core/cultivation_manager.py` 的闭关基础修为），产出 `exp-curve-report.md`、`sim_exp_curve.py`、`balance-recommendations.md`。 |

## 使用约定

- 新增设计资料（调研、公式推演、竞品参考、平衡性演算等）请放入本目录并登记到上表。
- **本项目的设计资料必须与代码实现保持同步**：任何影响游戏玩法的修改（即使很小），都应同步修正本目录中涉及的设计文档；纯 bug 修复除外（见插件根目录 `AGENTS.md` §14）。
- 正式的变更提案与设计决策走 OpenSpec 流程（`openspec/changes/`），本目录仅存放支撑性资料。
