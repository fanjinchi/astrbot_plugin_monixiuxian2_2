# Journal - guigui (Part 1)

> AI development session journal
> Started: 2026-10-08

---



## Session 1: 气血基座：评审-修复-归档闭环
<!-- trellis-session: v=2 fp=5cae3403a60e16d7 -->

**Date**: 2026-10-12
**Task**: 气血基座：评审-修复-归档闭环
**Branch**: `main`

### Summary

玩家持续气血领域基座（三层字段+v35迁移+HealthService惰性恢复）实现经三轴评审：P0 锚点内存-DB不同步、P1 低上限恢复死区、P2×9。全部修复（update_player 排除领域独占列、busy 钩子同步内存、恢复每分钟保底1点等）+4回归测试，复查子代理实证放行。972 tests 绿。spec 补「领域独占列被通用update回刷」条目。遗留：bd-hnz 解析链合并（含面板心法加成丢失实bug）。

### Git Commits

| Hash | Message |
|------|---------|
| `3883670` | 气血: 玩家持续气血领域基座（三层字段 + v35 迁移 + 惰性恢复域） |
| `04d87b2` | docs(spec): 数据库常见错误补「领域独占列被通用 update 回刷」条目（气血基座 P0 教训） |

### Status

[OK] **Completed**


## Session 2: PVE Child B：固定名册内容管线与敌人运行时基座（含双轴评审整改）
<!-- trellis-session: v=2 fp=1c4895ab4e7ebce1 -->

**Date**: 2026-10-12
**Task**: PVE Child B：固定名册内容管线与敌人运行时基座（含双轴评审整改）
**Branch**: `main`

### Summary

批准进入 Phase 2 后完成 child B 实施：core/enemy_schema.py（schema v2 + 28+4 profile 校验 + 机制常数单一真相，与 sim_pve_acceptance 互锁）；sync_content_to_config.py 敌人域双模式（preview 只读 CSV 渲染 / 正式写 fail-closed 审批闸门：status=final + manifest SHA-256/数据集/列范围/叙事决策，CLI 守卫拒写 config/）；managers/enemy_catalog.py 不可变 catalog+resolver（(段位,档位) 索引、绝对面板、难度单点只乘伤害）+ 唯一 build_enemy_fighter（level_index/crit /100/触发技/绝招，附录 C.4 蒙手口径）；旧动态路径语义修正（difficulty_coefficients 死配置清尸、两条 spawn 难度只乘伤害、Enemy 统一档案字段、守护组 passthrough 兼容）；default_configs 守护 crit 单位对齐消除全新安装暴击≈0 回归。验收：28+4 四层一致 32 例 + SimParity 常数互锁 + 难度/专项组/mapper 回归 + 24 例同步闸门测试，pytest 1057 passed、ruff 全绿。双轴评审（code-review skill）确认 1 真实回归 + 2 证据虚报 + 断言恒真等问题，整改 d840258 后独立复审 7/7 通过，建议级 nit 6ae7ab3 收口。边界保持：未正式 sync、未切流、无 Step 7 经济；Batch 5 复验+切流挂 bd hua。版本 v3.19.0，README/current-design-report/pve-enemy-design 实施状态/api-overview 已同步。

### Git Commits

| Hash | Message |
|------|---------|
| `35a9df6` | feat(pve): 固定名册内容管线与敌人运行时基座（Trellis child B） |
| `d840258` | fix(pve): 落实 Child B 双轴评审整改（断言修正 + 默认表暴击单位 + preview 写守卫 + 证据校准） |
| `6ae7ab3` | docs(pve): 复审建议级措辞收敛（from_dict 拦截口径与 trigger skill 数值来源描述） |

### Status

[OK] **Completed**


## Session 3: child P：PVE 持久化与事务基座（Batch 2）完成 + 评审闭环
<!-- trellis-session: v=2 fp=73b8ce9f5e8c8e7e -->

**Date**: 2026-10-13
**Task**: child P：PVE 持久化与事务基座（Batch 2）完成 + 评审闭环
**Branch**: `main`

### Summary

落地迁移链 v36–v38（11 张 PVE 域表，fresh==upgrade 共享 DDL）、data/ 层 20 处裸 commit 事务叶子门控、pve_repository 幂等/CAS/claim/封顶/外发表达原语、时间快进注册 14 条目/13 域；两轴 code-review（0 项 P0/P1）后修正 docstring 契约、cas_version 缺键显式报错、补 foreign_key_check 与 gather 真并发测试、metadata/README 同步 v3.20.0；pytest 1097 passed、ruff format/check 含 tests 全绿；bd qbo 登记 data/ 外 6 处裸 commit 遗留，归 children C/D/E。

### Git Commits

| Hash | Message |
|------|---------|
| `a4ddaed` | feat(data): 冻结 PVE 持久化版本链并落地事务与幂等基座 |
| `44cd8e0` | fix(pve): 评审修正——cas_version 严格校验、事务契约文档与并发/FK 验证补强 |

### Status

[OK] **Completed**


## Session 4: child C 历练结算状态机：六轮复核逼出的四处永久锁死/发奖漏洞与并发收尾收口
<!-- trellis-session: v=2 fp=e6a8d51ad405ac09 -->

**Date**: 2026-10-14
**Task**: child C 历练结算状态机：六轮复核逼出的四处永久锁死/发奖漏洞与并发收尾收口
**Branch**: `main`

### Summary

交付 PVE 历练持久结算与战前抉择（迎战/逃跑、甲案两条强制出路提示、休整全局窗口、逃跑两段公式临时默认值、GM 强制迎战/触发结算两条命令、v39 迁移与列、取消气血恢复忙碌闸门）。六轮独立复核共修四处：① 孤儿 pending_choice 可被后续任一次忙碌消费发奖并抹掉当前忙碌（加归属闸门 + 拦截器同口径门控）；② 升级即在途的历练忙碌没有 run id，补建单据不落回 extra → 迎战/逃跑全拒、每次点击再补一张单（同一事务 stamp_extra + settlement:{run_id} 同形）；③ 该补建的 run id 由 uuid 改 create_time 派生确定性 id，让并发双击靠 UNIQUE + 冲突回读收敛为一条事实；④ 确定性 id 反过来暴露落败方陈旧快照全列回写把已 clear 的忙碌复活成「历练中」→ 永久锁死（insert 的 created 闸门：只有真正落单那一路才 stamp）。第六轮另报同类 P2（GM 用事务前 user_cd 直写，AGENTS §2 既有例外），按「单据终态 ⇒ 不持有该场历练的忙碌」这条不变式在 _replay_terminal 补带归属判定的兜底收尾（读库里当下的 user_cd，期间已开更新一场则不误清），GM 自身命令写完立刻调用 finish_adventure，复活在同一条命令内即被吃掉，不再逐点堵写入者。驳回第六轮一处异议：它用包装 insert_settlement 强制 created=True 做突变得 0/20 复活、据此说新断言不是稳定钉子；本会话把代码原地还原成 if minted: 跑该用例 20 轮 = 20/20 红（突变方式多了一次 await，把 stamp 挤到 clear 之前），故保留「去掉 created 闸门即红」，只补一处口径精确：复现要求真并发（同 tick gather，n=2 即够），相隔几十毫秒的人类连点在 finish_adventure 头部即被「不在历练中」挡掉，不是该 P1 的入口。质量门：pytest tests/ 1143 passed（状态机 41 + GM 65，全部关键修复做过突变验证）、ruff format --check 127 files unchanged、插件范围 ruff check 全绿；本地四个 commit，工作树干净，未 push。剩余：AC6 真实环境 TTK/胜率/资源税回归与迎战/逃跑真实管线用例待用户发起（bd -2v2 已补第 5 条自愈场景），flee 三档数值待封板（bd -9hq），结构欠账与终态收尾分处两处登记在 bd -aue，平台事务隐患 bd -dfb 仍开。按用户决定任务保持 in_progress、不归档，仅记本 journal。

### Git Commits

| Hash | Message |
|------|---------|
| `2dc1b70` | feat(pve): 取消气血恢复忙碌闸门并新增 v39 结算状态机列 |
| `d1c5190` | feat(pve): 历练结算状态机与战前迎战/逃跑（child C） |
| `a1ea995` | fix(pve): 并发落败方不再复活已收尾的历练忙碌 |
| `aac9a98` | fix(pve): 终态重放补收尾被陈旧快照复活的历练忙碌 |

### Status

[OK] **Completed**
