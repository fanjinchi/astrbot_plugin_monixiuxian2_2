## 1. 插件骨架与适配器注册

- [x] 1.1 创建 `testplatform_plugin/` 插件骨架：`metadata.yaml`（name `astrbot_plugin_testplatform`、version、display_name 中文、astrbot_version 范围）、`requirements.txt`（`aiohttp>=3.9`）、`main.py`（Star 子类，`__init__` 接收 AstrBotConfig，定义 plugin 目录路径与数据目录 `get_astrbot_data_path()/plugin_data/astrbot_plugin_testplatform`）
- [x] 1.2 在 `adapter/webtest_adapter.py` 用 `@register_platform_adapter("webtest", ...)` 注册 `WebTestAdapter(Platform)`：实现 `meta()`（PlatformMetadata，`support_proactive_message=True`）、`run()`（启动 aiohttp 服务协程 + 挂起直至关闭事件）、`terminate()`；main.py 顶部 import 该模块使注册生效
- [ ] 1.3 验证：插件加载后 Dashboard 平台列表出现 webtest 适配器且可启用；热重载不报注册冲突（注销机制生效）

## 2. 持久化层

- [x] 2.1 实现 `storage/db.py`：aiosqlite 连接 `data/plugin_data/astrbot_plugin_testplatform/test_platform.db`；建表 `conversations`、`players`、`messages`（含 direction in/out/system、sender、text、rich JSON、created_at）、`annotations`（message_id 外键、text、updated_at）；启动时 `ensure_connection()` + 幂等建表（CREATE IF NOT EXISTS）
- [x] 2.2 实现会话 CRUD（create/list/archive/delete、重开）与消息追加/分页读取（`after` 增量）、批注 CRUD，全部 async；删除会话级联删除其消息与批注
- [x] 2.3 验证：单测覆盖 CRUD 与重启恢复（同实例重建连接后数据完整）

## 3. 入站管线（消息注入）

- [x] 3.1 实现消息构造 `build_abm(conversation, player, text)`：`AstrBotMessage` 设置 `sender=MessageMember(nickname, user_id)`、`type=FRIEND_MESSAGE/GROUP_MESSAGE`（群聊带 `group_id`）、`session_id`（私聊 `webtest!{user_id}!{uid}`、群聊 `webtest!group!{group_id}`）、唯一 `message_id`、时间戳
- [x] 3.2 实现注入入口 `inject_message(conversation_id, player_id, text)`：查会话/玩家 → 构造 abm → `commit_event(create_event(abm))` → 立即以 direction=in 持久化该消息
- [ ] 3.3 验证：注入"我要修仙"等指令，修仙插件以真实 Handler 响应（玩家入库、状态流转与真实平台一致）；白名单：群会话 group_id 未入修仙插件 whitelist_groups 时 `require_whitelist` 指令被拒并提示

## 4. 出站捕获

- [x] 4.1 实现 `WebTestMessageEvent(AstrMessageEvent)` 子类，重写 `send()`：MessageChain → 纯文本（Plain 拼接，Image/File 等非文本段转描述写入 rich JSON）→ 追加 direction=out 消息 → 推 WebSocket → 调 super
- [x] 4.2 重写 `send_streaming()`：分片累积文本并逐片追加/更新 feed（尽力呈现，不阻塞管线）
- [x] 4.3 适配器重写 `send_by_session(session, chain)`：从 session 解析会话（按 `_extract_conversation_id` 风格解析 `webtest!...`，私聊/群聊均支持）→ 会话不存在则自动创建（标记 system-created）→ 追加 direction=out → 推 WebSocket → 调 super
- [ ] 4.4 验证：指令回复（event.send 路径）与定时广播（Boss 生成等 `context.send_message` 路径）都出现在对应会话 feed 并持久化；主动消息到未知群自动建会话

## 5. Web 服务与 REST API

- [x] 5.1 `server/app.py`：aiohttp web 应用，`host=127.0.0.1`、`port` 与 `access_token` 从 AstrBotConfig 读取；令牌中间件：设置令牌后所有 `/api/*` 与 WS 握手校验（缺失/错误 → 401）；静态目录指向 `webui/`
- [x] 5.2 REST 端点：`GET/POST /api/conversations`、`PATCH/DELETE /api/conversations/{id}`、`GET /api/conversations/{id}/messages?after=&limit=`、`POST /api/conversations/{id}/messages`（body: sender/text）、`GET/POST/PATCH/DELETE /api/messages/{mid}/annotation`、`GET /api/players`；错误统一 JSON `{"error": ...}` + 恰当状态码
- [x] 5.3 WebSocket `/ws`：连接即推全量会话列表与当前会话消息，之后增量推送新消息与批注变更
- [x] 5.4 验证：curl 冒烟（建会话→注入→轮询 messages 出现机器人回复→加批注→归档→注入被拒）；错误路径（错令牌 401、未知会话 404）

## 6. 前端

- [x] 6.1 `webui/index.html` + `app.js` + `style.css`：会话栏（列表/新建：类型、群 ID、成员、归档按钮）、消息流（玩家/机器人/系统消息分侧显示，含 sender、时间、批注角标）、输入框（选 sender + 文本注入）、批注面板（添加/编辑/删除）
- [x] 6.2 WebSocket 实时更新：新消息/批注到达自动渲染；归档会话只读；本地无构建链、无外部 CDN 依赖（离线可用）
- [ ] 6.3 验证：浏览器全流程走通（建群会话→多个玩家发消息→看修仙插件回复→批注→刷新后状态完整）

## 7. CLI（AI 侧接口）

- [x] 7.1 `scripts/test_platform_cli.py`（argparse）：子命令 `conversations`（list/create/archive/delete）、`send`、`feed --after --json`、`wait --expect 子串 --timeout`、`annotations`、`annotate`；`--url`/`--token` 与 `WEBTEST_URL`/`WEBTEST_TOKEN` 环境变量；`--json` 输出机器可读
- [x] 7.2 `wait` 实现：轮询 `feed --after` 直至出现包含 expect 子串的机器人消息或超时（退出码 0/非 0 区分），供 AI 测试脚本同步等待
- [x] 7.3 验证：AI 用 CLI 完成"注入→等待回复→读批注"闭环；README 附全部子命令用法示例

## 8. 测试用例管理

- [x] 8.1 用例存储与校验：`cases/` 目录 JSON 用例（name/description(必填：测试目的与场景)/scenario(必填：前置条件与涉及功能)/tags/conversation{kind, group_id?, pin_players?}/steps[{type: send|expect|sleep, note?}]），加载器 + 结构校验（非法用例、缺必填说明字段报错并跳过）；DB 新增 `case_runs` 表（case、status、逐步骤结果含实际回复、起止时间）
- [x] 8.2 运行器 `cases/runner.py`：每次运行创建临时会话（system-created）与唯一玩家身份（`case_{name}_{run}_{player}`；pin_players 钉住固定身份）→ 顺序执行：send 注入 / expect 轮询新 out 消息子串或正则匹配（超时失败）/ sleep 等待；结果与**轨迹**写 `case_runs`：status、逐步骤结果、`case_snapshot`（用例文件内容快照）、`run_messages`（运行期全部消息交换快照含时序，不随会话删除丢失）
- [x] 8.3 CLI `case` 子命令：`list`（--tag 筛选）/ `new`（生成模板）/ `show` / `run <name>` / `run-all [--tag]`（全过退出码 0，有失败非 0）/ `runs list|show <run_id>`（AI 发起自动化测试与回看轨迹）；README 附用例编写示例与标签约定
- [x] 8.4 REST：`GET/POST /api/cases`、`PUT /api/cases/{name}`（更新用例内容，校验同加载器）、`GET/DELETE /api/cases/{name}`、`POST /api/cases/{name}/runs`、`GET /api/cases/{name}/runs`（含轨迹详情：消息时间线 + 步骤结果 + 用例版本）；Web UI 用例面板（新建/编辑[表单或 JSON 源码]/删除/一键运行、按标签筛选）+ **轨迹视图**：运行列表 → 单次运行消息时间线（步骤结果标注、**步骤说明 note**、批注入口、用例版本对比）
- [ ] 8.5 验证：写"修仙开局+闭关"示例用例（含 description/scenario/逐步骤 note），`case run` 通过；故意改错期望子串后运行失败且能读到实际回复；缺 description/scenario 的用例被校验拒绝；同一用例连续两次运行状态互不污染；删除运行会话后轨迹仍完整可看、可批注

## 9. 配置与文档

- [x] 9.1 `_conf_schema.json`：`host`、`port`、`access_token`、`default_players`（template_list：nickname/user_id）；README 说明：部署步骤、独立测试实例建议、将群会话 group_id 加入修仙插件白名单以测白名单行为、`unsupported_streaming_strategy=synchronous` 建议
- [x] 9.2 `design_docs/` 登记：README.md 资料清单加"测试平台"条目，新增文档说明平台架构、使用与**测试用例编写指南**（用例格式、必填说明字段与写法、步骤类型与 note 用法、标签约定、完整示例）；本仓库 README 追加更新日志条目（新增插件不影响游戏玩法数值，无 design_docs 数值同步义务）
- [x] 9.3 质量门禁：`uv run ruff format . && uv run ruff check .` 通过；`uv run python -m pytest tests/ -v`（既有测试不受影响）；metadata.yaml 版本号与 README 更新日志同步

## 10. 端到端验收

- [ ] 10.1 按 spec 场景逐条验收：真实管线（白名单拦截/忙碌状态/user_cd）、双向可见、注入接口、群聊多玩家独立身份、主动消息路由、批注持久化、会话归档、令牌 401、测试用例管理与一键验证（多次运行零污染、期望不匹配定位附实际回复）
- [ ] 10.2 与修仙插件协同冒烟：新会话从零开局（"我要修仙"→"闭关"→等待结算）全流程在网页可见，批注后 CLI 可读；提交前 git push
- [x] 10.3 隔离性验收：仅修改测试平台自身代码并重载后，`git status`/`git diff` 确认项目本体文件零改动；停用/卸载测试平台后修仙插件既有测试（`uv run python -m pytest tests/ -v`）全绿、行为不变；测试平台数据仅存在于 `data/plugin_data/astrbot_plugin_testplatform/`
