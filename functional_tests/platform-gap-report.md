# 网页测试平台能力差距报告

> 对着 `astrbot_plugin_testplatform`（webtest）实际 REST 能力与首批功能测试用例需求整理。
> 更新日期：2026-08-17。范围：`add-functional-test-suite` 第一批 28 条用例。

## Supported（可直接依赖）

| 能力 | 说明 | 用例依赖方式 |
|---|---|---|
| 用例 JSON 加载 | 顶层 `cases/*.json`，`name` 与文件名一致，自动校验必填字段 | 全部用例 |
| 步骤类型 `send` / `expect` / `sleep` | 真实注入消息并轮询回复 | 全部用例 |
| 文本断言 | 子串匹配；`re:` 前缀正则搜索 | 全部期望步骤 |
| 临时会话 | 每次运行新建会话，私聊玩家默认唯一 ID，轨迹独立保存 | 私聊冒烟用例 |
| 固定身份 `pin_players` | 群聊可钉住 GM/玩家真实 `user_id`，承担状态继承 | 全部 PvP / GM / 装备用例 |
| 群聊模拟 | 通过 `webtest!group!{group_id}` 走真实 AstrBot 群聊管线 | 全部群聊用例 |
| 运行结果 API | `POST /api/cases/{name}/runs`、`GET /api/runs/{id}` 返回步骤结果与消息轨迹 | 控制脚本 `run` / `export` |
| 消息流可见 | 会话 `feed` 双向消息、运行轨迹消息快照 | 排查断言超时 |
| 批注 | 网页端可对消息加批注，CLI/REST 可读 | 人工反馈闭环 |

## Partially supported（可用但有条件/需要绕行）

| 能力 | 现状 | 限制 | 绕行方式 |
|---|---|---|---|
| 群聊指令触发 | AstrBot 全局 `wake_prefix` 为 `#`，群聊必须带唤醒前缀 | 不带 `#` 时事件不会进入插件 Filter | 用例中所有群聊 `send` 统一加 `#` 前缀（已落地） |
| GM 身份 | 由插件 `ACCESS_CONTROL.GM_ADMINS` 控制，平台只负责投递 `user_id` | 必须先在 AstrBot 插件配置中加入固定 GM ID 并重载插件 | 测试实例已把 `900000001` 加入 `GM_ADMINS`；随环境配置文档记录 |
| 随机/概率效果验证 | 无 RNG seed，效果触发不稳定 | 单次运行不能证明“必然触发” | 使用 `--repeat N --fixture` 聚合文本证据，`_count_evidence` 统计触发次数 |
| 技能/功法授予 | 平台无“直接授予已学技能”命令 | 只能通过聊天命令学习，路径长且随机 | fixture 脚本直接写 `player_skills` 表，固定 `skill_id` 与星级 |
| 心法/功法装配 | 插件 GM `给予装备` 的 `_item_exists` 不识别 `heart_methods.json` | 无法用 GM 命令把心法放储物戒 | fixture 直接把 `长春功`/`疾风迅雷功` 写入 `storage_ring_items`；用例不再依赖 GM 给心法 |
| `@` 目标选择 | 平台只注入 `Plain` 文本，没有结构化 `At` 消息段 | GM 命令无法走 `@目标` 分支 | 用例使用纯数字 ID 参数，走 `_resolve_target` 数字分支 |
| 状态/DB 断言 | 平台只能断言“回复文本” | 不能直接查 DB 验证玩家属性/储物戒/`user_cd` | fixture 直接写库 + 战斗文本证据；GM 命令作为间接断言 |
| 时间推进 | 平台无虚拟时钟/时间加速 | 闭关、历练、Boss 等长周期不可真实等待 | 用例只做“入口可达”冒烟；需要结算时用插件 GM 强制结算命令 |
| 结果归档 | 平台有运行记录但没有“导出目录包” | 结果需自行拉取并组织 | 本项目 `scripts/test_suite_ctl.py export` 本地生成 `results/<date>_<target>/` |

## Unsupported（当前没有，列入平台增强建议）

| 能力 | 为什么需要 | 建议平台增强 |
|---|---|---|
| 随机数种子注入 | 效果矩阵需要可复现触发概率 | 适配器/运行器支持 `run.rng_seed`，并传递给插件测试入口或 mock `random` |
| 插件热重载运维端点 | 修改 `GM_ADMINS` 等初始化配置后必须手动 Dashboard 重载，AI 无法完成闭环 | 新增 `POST /api/ops/plugin-reload`（可选 `GET /api/ops/plugins`），内部调用 AstrBot `PluginService`，不依赖 Dashboard 登录态 |
| 结构化消息组件注入 | GM `@目标`、图片/文件/引用等路径无法覆盖 | `send` 步骤支持 `components` 数组（At/Image/Reply） |
| 直接 DB 断言 | 强断言需要核对库内落盘状态 | 提供 `GET /api/ops/db-query` 白名单查询或运行后 DB 快照 API |
| 时间加速/虚拟时钟 | 长周期玩法（闭关 1 分钟、Boss 冷却）不适合真实等待 | 支持 `run.time_offset` / `POST /api/ops/tick` 推进测试会话 |
| 平台内置结果导出 | 避免每个项目自己实现归档 | 参考 `export --date --target` 返回 summary/cases/messages 打包下载 |

## 已解决的平台侧问题

- `*.meta.json` 不再写入平台 `cases/` 目录：本项目 `sync-cases` 已改为只同步用例 JSON，并清理历史残留；平台 loader 侧也已过滤。
- 旧代码僵尸服务：平台已实现 `terminate()` 与实例重建逻辑，插件/平台代码改动后 Dashboard 重载即可生效。