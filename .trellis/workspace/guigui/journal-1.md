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
