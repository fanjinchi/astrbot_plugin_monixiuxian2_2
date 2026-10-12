# Implementation Plan: PVE 固定名册内容管线与敌人运行时

## Dependencies

- 可与玩家气血基座并行实施。
- 普通 PVE 和世界 Boss child 依赖本任务的 profile contract。
- 正式 sync 另需用户确认，不包含在代码实施批准中。

## Steps

1. 固定 enemies/world_bosses schema、version 和 negative validation fixtures。
2. 在同步脚本加入 adapter、确定性输出、内存/临时目录 preview 和正式写闸门：独立 `combat_status` + `--approval-manifest`（CSV SHA-256、获批数据集/列范围、叙事决策）。用真实 draft 只读生成 preview，但 draft/缺 manifest/hash 漂移/列越权均不得写正式 `config/`。
3. 实现不可变 Enemy/Boss catalog 与按 id/段位类别索引。
4. 替换普通怪动态派生为固定 resolver，集中“难度只乘伤害”。
5. 实现完整 profile→Fighter mapper。
6. 用兼容 adapter 保留秘境兽/守护者 group 路径。
7. 增加四层一致性、golden、专项组、难度回归，以及 draft/manifest/hash/列范围正式写负向测试；运行完整质量门。

## Rollback Point

adapter/loader 可在启用调用方前独立合入。若内容校验或运行时回归失败，不执行 sync、不切普通 PVE 调用方，旧 config 保持不变。

## Completion Evidence

- schema/adapter、approval manifest 格式与 combat/narrative 独立确认操作说明；
- 真实只读 CSV→临时 preview 的 28+4 validation/golden 结果（不覆盖正式 config、不能冒充正式同步）；
- profile/Fighter/专项组/难度测试；
- 完整质量门摘要。
