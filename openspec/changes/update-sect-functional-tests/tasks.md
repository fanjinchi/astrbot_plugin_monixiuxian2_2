# Tasks: update-sect-functional-tests

## 1. 存量用例迁移（依赖 unify-sect-commands 实施完成）

- [ ] 1.1 改写 `functional_tests/cases/sect/` 中 11 条引用旧指令的用例步骤为 `/宗门` 子命令形式：`sect-default-visible`（宗门 列表/创建）、`sect-join-level-gate`（加入/退出）、`sect-gm-set-position` 与 `sect-gm-set-contribution` 与 `sect-promotion`（宗门 晋升/信息）、`sect-master-chain-gm` 与 `sect-master-task-chain`（师承/捐献）、`sect-rejoin-retain` 与 `sect-leave-reclaim`（退出/加入/信息）、`sect-shop-discount`（宗门 晋升）、`sect-construction`（建设）
- [ ] 1.2 改写 `sect-content-filter`：移除「🏯 宗门悬赏分区」与「🔒 锁定行」相关断言；非成员秘境列表断言改用 `expect_not`（列表不含青云剑冢，平台 v0.2.0 负向断言）＋探索被拒兜底，成员可见可进断言保留，宗门悬赏相关步骤移入新用例文件

## 2. 新增用例

- [ ] 2.1 `sect-command-entry.json`：无参数导航帮助、未知子命令拒绝、缺参子命令用法提示（对照 spec「统一指令入口与子命令路由」）
- [ ] 2.2 `sect-bounty-lifecycle.json`：成员「宗门 悬赏」查看/接取 307/进度/GM 触发历练结算推进/完成 完整闭环（307 `progress_tags` 含 `adventure_scout`、`min_target=2`，走巡山路线确定性达成；用例声明 `deterministic: true` + seed 固定随机池抽样）；首尾用 GM「清除悬赏」清理状态（依赖 `unify-sect-commands` 任务 2.5）；无宗门玩家「宗门 悬赏」拒绝
- [ ] 2.3 `sect-bounty-split.json`：全局「接取悬赏 307/308」拒绝并提示宗门入口；「宗门 悬赏 接取 <全局编号>」拒绝；跨类型状态/完成/放弃拒绝提示；开场用 GM「清除悬赏」保证无冷却/活跃残留（分流校验先于冷却检查，见 design 决策 4）
- [ ] 2.4 `sect-shop.json`：商店列表展示、GM 设置贡献后购买成功（断言到账提示）、贡献不足拒绝、职阶门槛拒绝/锁定标注、无宗门玩家拒绝
- [ ] 2.5 `sect-adventure-event-marker.json`：声明 `deterministic: true` + seed（默认 42）+ GM 触发历练结算断言「🏯 宗门际遇」出现，必要时 `--repeat ≥10` 采样计数兜底，普通事件结算结构对照不变

## 3. 缺口报告与同步

- [ ] 3.1 更新 `functional_tests/platform-gap-report.md`：反向断言（expect_not）与随机种子注入（deterministic/seed）行改列为已支持并移除对应绕行；悬赏冷却清理改由 GM「清除悬赏」覆盖（登记该 GM 的引入背景）；新增 one-shot 编排能力；如新增其他受限点一并登记
- [ ] 3.2 `uv run python scripts/test_suite_ctl.py sync-cases` 校验全部用例合法且名称唯一，同步到测试平台；随后 `case check --source` 确认源与平台副本一致（防漏 sync 跑旧用例）

## 4. 文案校对与执行归档

- [ ] 4.1 `unify-sect-commands` 实施完成并热重载后，校对全部新/改用例的断言文案与最终实现一致
- [ ] 4.2 以 one-shot 管线执行：`case run-all --tag sect --quiet --sync-from ./cases --reload astrbot_plugin_monixiuxian2_2 --export ./results`（必要时单用例 `case run --repeat N --sync-from --reload` 聚合），全部通过
- [ ] 4.3 归档 one-shot 导出的结果至 `functional_tests/results/<date>_sect-commands/`（含 summary.json 通过/失败清单）；发现的玩法 Bug 用 `bd` 登记
