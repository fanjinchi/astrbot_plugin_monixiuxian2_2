# Handoff — GM「设置战斗气血」+ 23 条 PvP 用例 v35 适配（方案 A）

> **为什么放在仓库里**：本环境的 `/tmp` 会在工具执行之间被清空（实测两次），跨窗口交接必须用仓库内路径。本文所在目录 `.trellis/workspace/guigui/` 是 Trellis 的开发者工作区，另一个窗口打开同一仓库即可直接读。

**日期**：2026-10-17
**仓库**：`/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2`（分支 `main`，HEAD `418cdfa`，工作树干净）
**任务号**：bd `astrbot_plugin_monixiuxian2_2-xtv`（open，P2）——完整证据、影响面、两个备选方案都在 `bd show astrbot_plugin_monixiuxian2_2-xtv --json` 里，本文只写"怎么做"。
**来源**：全列回写收口任务（bd `-546`，已归档）→ 用户批准跑真实环境回归 → 发现 v35 遗留 → 用户拍板走方案 A，交给新窗口执行。

## 一句话

v35（child A 气血分层，2026-10-12）之后「修仙GM 设置气血」只改 `base_hp`、不动 `current_hp`，而 23 条 PvP 用例仍靠它构造 8000 血长局 → 战斗 1~3 回合结束，"8~25% 效果单场必中"的前提塌了。方案 A：**新增 GM 子命令「设置战斗气血」，一次把 `base_hp` 与 `current_hp` 都设成目标值**，再把 23 条用例的 `设置气血` 换成它，跑 pvp 全矩阵验证。

## 要做的事（按顺序）

### 1. 加 GM 子命令（约 15 行）

- `core/gm_manager.py` 命令路由表 `self._commands`（约 119-131 行，`"设置气血": self.cmd_set_hp` 那行下面）注册 `"设置战斗气血": self.cmd_set_battle_hp`
- 新方法放在 `cmd_set_hp`（724-739）旁边：先 `await self._set_numeric_attr(event, args, "气血", "base_hp", "气血")` 抬上限并拿到回执，再 `player = await self._get_player(target_id)` + `await self.health_service.set_current_hp(player, value)`（`core/health.py:251`，自带 settle + clamp）。`health_service is None` 的独立测试装配下退化为 `player.current_hp = min(value, 上限)` + `await self.db.update_player(player)`
- 帮助文本（`help_text` 约 348-357 的「📖 角色属性」段）加一行：`  设置战斗气血 [@玩家/ID] <数值> （同时设上限与当前气血）`
- 单测：`tests/test_gm_manager.py:282` 的 `cmd_set_hp` 用例是模板，照抄一条 `cmd_set_battle_hp`（覆盖 health_service 已接线 / 未接线两条分支）
- 按 `AGENTS.md` §7 同步：`metadata.yaml` 版本 + `README.md` 更新日志（`handlers/misc_handler.py:196` 只有一行总览，通常无需改）

### 2. 替换 23 条用例

清单（`functional_tests/cases/pvp/`）：`legacy-basic`、`pvp-basic-duel`、`pvp-heart-passive`、`pvp-weapon-trigger`、`pvp-ultimate-{damage,dot,heal,survive}`、`pvp-effect-{buff,combo,counter,damage_bonus,damage_reduction,debuff,dot,fatigue,heal,pierce,reflect,stun,survive,unavoidable,vampire}`。

- 文本 `#修仙GM 设置气血 <id> 8000` → `#修仙GM 设置战斗气血 <id> 8000`（每条用例 2 处，共 46 处）
- 同时改 `note`：现有 note 写"GM 设置气血同时抬高 hp 与 max_hp"，改后应写"设置战斗气血同时设上限与当前气血"
- 建议脚本批量替换 + 逐条 `git diff` 目检

### 3. 推到平台 + 跑

**不能用** `sync-cases`：平台 cases 目录在沙箱工作区之外、对沙箱只读。改用平台 API：

```
POST /api/cases         body {"name": <用例名>, "content": <完整用例 JSON>}   # 新建 → 201
PUT  /api/cases/<name>  body {"content": <完整用例 JSON>}                     # 更新 → 200
```

（本会话已用同样方式推过 3 条 economy 用例；平台地址 `http://127.0.0.1:8765`，无 token。）

```
cd /home/guigui/code/AstrBot/data/plugins/astrbot_plugin_monixiuxian2_2
python3 scripts/test_suite_ctl.py run --tag pvp --reload astrbot_plugin_monixiuxian2_2
python3 scripts/test_suite_ctl.py run --case legacy-basic
python3 scripts/test_suite_ctl.py export --target pvp-v35-adaptation
```

- 平台 CLI 的 `--sync-from` 只吃拍平目录（非递归），**不要**用它同步分域子目录
- **禁止并发跑批**（同一套固定测试 ID 与 `.fixture-backup.json` 会互相覆盖）
- 查单条运行详情：`python3 data/plugins/astrbot_plugin_testplatform/scripts/test_platform_cli.py runs show --id <id>` → 解析 `.steps_result[]`，`ok=false` 的 `detail` / `actual` 有真凭据

### 4. 判定剩余失败

这套矩阵自 **2026-09-28** 未跑过（v35 是 10-12），修好本轮后可能还冒出别的 v35 漂移。逐条判"v35 遗留 / 真回归"，不要把既有问题算到本次头上；新发现按项目规矩开 bd（`bd create ... --json`），关联用 `discovered-from`。

## 环境坑（会绊住你）

- **`/tmp` 不可用于交接**：文件在工具执行之间会被清空；临时脚本写进插件目录（`.tmp_*.py`）并立刻删
- 沙箱是 `workspace-write`：AstrBot 根目录与 `data/plugin_data/**` **不可写**。uv/ruff 必须带缓存目录：
  `cd /home/guigui/code/AstrBot && UV_CACHE_DIR=/tmp/uvcache RUFF_CACHE_DIR=/tmp/ruffcache uv run ...`
- 平台：`curl -s http://127.0.0.1:8765/api/status` 应见 `"adapter_ready": true`；平台 CLI 在 `data/plugins/astrbot_plugin_testplatform/scripts/test_platform_cli.py`（相对 AstrBot 根）
- 测试库：`data/plugin_data/astrbot_plugin_monixiuxian2_2/xiuxian_data_lite.db`（一次性实例；**别碰**生产 `xiuxian_data_v2.db`）
- fixture profile：`pvp` / `sect` / `breakthrough` / `economy`；PvP 用例走 `pvp`（`_upsert_player` 重置 3 个固定 ID：`base_hp=current_hp=1000`、gold 10 万、乾坤储物戒 120 格、1 级）
- GM 身份：`gm` = `900000001` 必须在 `GM_ADMINS`；群 `webtest_pvp_001`；群消息文本必须以 `#` 开头
- 质量门：`uv run python -m pytest data/plugins/astrbot_plugin_monixiuxian2_2/tests/ -q`（**基线 1157 passed**）+ `uv run ruff check` 源码目录（managers/ tests/ core/ handlers/ data/ main.py）

## 已完成、别重做

- 全列回写收口（bd `-546` 写入端止血）已完成并归档：`.trellis/tasks/archive/2026-10/10-15-full-row-write-containment/`（PRD 含两轮评审记录）；提交 `5e9c169` / `3352164` / `3531793`
- 本轮功能回归结果：`core-smoke` 7/8（唯一失败就是 `-xtv`）、`daily-checkin-basic` ✓、`economy` 5/5（含 3 条新用例）、`pve-smoke` ✓
- 已修并 closed：`-eir`（fixture 脚本写已改名的 `players.hp`，提交 `b1db534`；修复后 5 条原本崩在 pre_run_hook 的用例恢复）
- 用户并行修并 closed：`-hbz`（破境丹误服，提交 `1660fb1`）——**不要重复动**
- 新增用例与 fixture profile：提交 `8555ef5`（`economy` profile + 洞天/灵田/储物戒 3 条用例 + 归档 `functional_tests/results/2026-10-17_economy-regression/`）
- 长期债（不在本任务范围）：`-546`（`update_player` 列级/diff API；`_replay_terminal` 收尾整行写仍会回退并发写入的非效果列）

## 关键路径速查

- GM：`core/gm_manager.py`（命令表 ~119-131、`cmd_set_hp` 724-739、`_set_numeric_attr` ~660-710、`help_text` ~348）
- 健康域：`core/health.py`（`set_current_hp` 251、`clamp_current_hp` 221；三层语义见模块 docstring）
- 用例协议：`functional_tests/README.md`（断言锚点原则、单 `send` 单断言、fixture profile 清单、并发约束）
- fixture 脚本：`scripts/test_suite_ctl.py`（`_upsert_player` ~942、`cmd_fixture` 1232-1320、argparse ~1384-1424）
- 平台 skill：`.agents/skills/testing-astrbot-plugins-via-webtest/SKILL.md`（符号链接，操作细节以它为准）

## Suggested skills

- `testing-astrbot-plugins-via-webtest` — 推/跑平台用例、查 run 详情（本任务的验证手段）
- `trellis-before-dev` — 动 `gm_manager` 前读 `.trellis/spec/backend/*`
- `tdd` — 加 GM 子命令时先写单测
- `trellis-check` 或 `code-review` — 提交前复核（本项目惯例：P0/P1 修完再叫一轮独立复看）
- `trellis-finish-work` — 收尾（journal / 归档 / commit 提醒）
