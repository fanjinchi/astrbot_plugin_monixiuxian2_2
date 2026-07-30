# design_docs — 设计资料库

本目录存放供设计（重新设计数值、战斗、技能等系统）时查阅的参考资料，供开发者与 AI 助手读取。

## 资料清单

| 文件 | 说明 |
|---|---|
| `current-design-report.md` | 现有系统架构与数值设计报告（基于源码静态分析，含 `file:line` 引用，数据库以 migration v21 为准）。作为数值/战斗/技能重设计的初始基线资料。 |
| `mybrute/` | My Brute（Motion-Twin 自动战斗页游）设计调研：wiki 资料整理 + 网络调研笔记。 |
| `qpet-daledou/` | Q宠大乐斗（早期版本，约 2010-2012）设计调研笔记。 |
| `attribute-growth/` | 属性成长与镜像战 TTK 调研：本插件/My Brute/Q宠大乐斗相同个体战斗回合数 CSV（蒙特卡洛模拟）、业界自动战斗游戏平衡方案网络调研、汇总分析（入口 `attribute-growth-analysis.md`），及成长/加成平衡设计方案 `growth-balance-proposals.md`。 |

## 使用约定

- 新增设计资料（调研、公式推演、竞品参考、平衡性演算等）请放入本目录并登记到上表。
- 正式的变更提案与设计决策走 OpenSpec 流程（`openspec/changes/`），本目录仅存放支撑性资料。
