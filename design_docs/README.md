# design_docs — 设计资料库

本目录存放供设计（重新设计数值、战斗、技能等系统）时查阅的参考资料，供开发者与 AI 助手读取。

**类型标注**：资料清单中每项标注内容归属——

- **本项目**：基于本插件（AstrBot 修仙插件）源码、配置或运行数据产出的分析、模拟与设计，反映本项目当前设计事实；
- **外部参考**：其他游戏（My Brute、Q宠大乐斗等）或网络调研资料，仅作设计蓝本与灵感来源，**不代表本项目现状**；
- **混合**：目录内同时包含本项目产出与外部参考，通常可按文件名前缀区分（如 `xiuxian-*` / `worker-xiuxian-*` 为本项目，`mybrute-*` / `qpet-*` 为竞品）。

## 资料清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `current-design-report.md` | 本项目 | 现有系统架构与数值设计报告（基于源码静态分析，含 `file:line` 引用，数据库以 migration v31 为准）。创建于 2026-07-29、最近更新 2026-08-20（头部有文档状态标注），作为数值/战斗/技能重设计的**活基线资料**（非归档）；架构总览以 `project-architecture.md` 为准。 |
| `project-architecture.md` | 本项目 | **架构与系统功能设计总览**（2026-08-07 建立）：分层架构与关键机制、20 个子系统功能设计表（入口/核心数值/冷却）、openspec 契约摘要与滞后点、重设计里程碑时间线、进行中工作（bd）对照、资料导航与维护约定。新增/修改功能前建议先读。 |
| `world-bible.md` | 本项目 | **世界观设定集（World Bible）**（2026-08-24 建立，openspec change `worldview-bible`）：摸鱼修仙界主线性（灵气枯竭→复苏）、基调与玩梗尺度（合格/不合格对照）、地理（收编 5 地名+妖域四层）、势力（青云门/合欢宗收编+宗门-路线绑定规则）、修炼体系叙事化（灵/体双词汇表）、命名规范（品级词+禁用词）、既有内容收编清单。**全部内容文案的唯一事实来源**。世界观/文案基调变更时须同步本文。 |
| `api-overview.md` | 本项目 | **关键 API 速查**（2026-08-11 建立）：指令→main.py 路由→handlers→managers→core→data 全链路索引，各层关键入口方法与作用、横切工具（状态/事务/定时任务）、给 AI 的检索路径。改动公开方法或新增子系统时须同步本表。 |
| `test-platform.md` | 本项目 | **网页端测试平台设计文档**（2026-08-15 建立，openspec change `add-web-test-platform`）：配套工具（非玩法系统）——平台适配器接入真实管线机制、用例引擎与校验规则、后台运行接口（202/409）、REST/CLI 速查、Dashboard 嵌入页、配置项、隔离性保证。平台功能变更时同步本表。 |
| `../functional_tests/` | 本项目 | **项目内功能测试套件**（2026-08-17 建立，openspec change `add-functional-test-suite`）：用例源文件（`cases/`）、结果归档（`results/`）、运行/同步/导出脚本与说明（`README.md`）。 |
| `../functional_tests/platform-gap-report.md` | 本项目 | **测试平台能力差距报告**（2026-08-17 建立）：按 Supported / Partially supported / Unsupported 分类当前平台能力限制与增强建议（RNG seed、直接授予功法、结构化 At、DB 断言、时间加速、结果导出 API 等）。 |
| `mybrute/` | 外部参考 | My Brute（Motion-Twin 自动战斗页游）设计调研：wiki 资料整理 + 网络调研笔记。 |
| `qpet-daledou/` | 外部参考 | Q宠大乐斗（早期版本，约 2010-2012）设计调研笔记。 |
| `attribute-growth/` | 混合 | 属性成长与镜像战 TTK 调研：`xiuxian-*`、`worker-xiuxian-report.md` 为本插件蒙特卡洛模拟；`mybrute-*`、`qpet-*` 为竞品模拟；另含业界自动战斗游戏平衡方案网络调研（`auto-battle-balance-web-research.md`）。汇总分析入口 `attribute-growth-analysis.md`，本项目成长/加成平衡设计方案 `growth-balance-proposals.md`。 |
| `content-design/` | 本项目 | 玩家侧内容设计工作区（武器/功法/心法定稿数值，最终产出 `config/weapons.json` / `skills.json` / `heart_methods.json`）；设计蓝本取自 `mybrute/`、`qpet-daledou/` 外部调研。 |
| `level-exp-curve/` | 本项目 | 升级经验曲线蒙特卡洛模拟与平衡建议（基于本插件修炼收益假设，如 `core/cultivation_manager.py` 的闭关基础修为），产出 `exp-curve-report.md`、`sim_exp_curve.py`、`balance-recommendations.md`。 |
| `sect-system-design.md` | 本项目 | **宗门系统扩展总设计**（2026-08-18 建立，2026-08-21 回写 `unify-sect-commands` 指令收敛）：默认宗门（系统势力）配置化、宗门建设/师承任务线/职阶晋升、宗门商店（一期），毁灭与重建（二期）、NPC 人格化预留（三期）；全部宗门功能收敛为「宗门」单指令+子命令（含悬赏独立入口/秘境仅本宗可见/历练事件标记）；含策划配置速查表与架构改造清单。宗门玩法变更时同步本文。 |
| `novel-research/` | 外部参考 | 修仙小说世界观素材提取库（openspec change `read-novels-extract-content` 产出）：**10 本小说世界观全收录**（境界突破/宗门情节/道具法宝/功法神通/丹药灵药/地名势力/事件奇遇/战斗描写/人物关系 9 维度 + 玩法映射标签），供修仙玩法设计取材。文件：`extract-fanren.md`（凡人修仙传，全本 2446 章）`extract-xianni.md`（仙逆，全本 2088+后记）`extract-zhetian.md`（遮天，全本 1822+大结局）`extract-zhuxian.md`（诛仙，全本 293 章）`extract-yinianyongheng.md`（一念永恒，精读 654 章+网络补足）`extract-woshixiongshizaitaiwenjianle.md`（我师兄实在太稳健了，采样精读 50 章）`extract-dafengdagengren.md`（大奉打更人，采样精读 44 章）`extract-guimizhizhu.md`（诡秘之主，采样精读 24 章）`extract-daoguiyixian.md`（道诡异仙，采样精读 33 章+网络补足）`extract-fubenshidao.md`（佛本是道，采样精读 25 章）。另含 3 本早期专项笔记（`01-fanren-xiuxian-chuan.md`、`02-xian-ni.md`）与**可复用模板清单**（`novel-research/README.md`，各维度玩法设计模板索引）。 |

## 使用约定

- 新增设计资料（调研、公式推演、竞品参考、平衡性演算等）请放入本目录并登记到上表。
- **本项目的设计资料必须与代码实现保持同步**：任何影响游戏玩法的修改（即使很小），都应同步修正本目录中涉及的设计文档；纯 bug 修复除外（见插件根目录 `AGENTS.md` §14）。
- 正式的变更提案与设计决策走 OpenSpec 流程（`openspec/changes/`），本目录仅存放支撑性资料。
