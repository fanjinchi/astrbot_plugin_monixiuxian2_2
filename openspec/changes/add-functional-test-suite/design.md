## Context

动机见 proposal.md。已核实的关键现状与约束：

- 测试平台已提供：私聊/群聊会话、多玩家、`pin_players` 固定身份、`send/expect/sleep` 步骤、运行轨迹持久化、标签批量运行、REST/CLI。
- 平台用例加载器只读 `data/plugin_data/astrbot_plugin_testplatform/cases/*.json` **顶层文件**，不扫描子目录；用例 `name` 必须等于文件名。
- 平台运行器默认生成非数字唯一 user_id；`pin_players` 可钉数字 ID。修仙插件 `切磋/决斗` 的目标解析支持「纯数字参数」和 `@`，但平台注入消息目前不构造结构化 `At` 消息段，只能靠数字 ID 文本兜底。
- 修仙插件 GM 命令可设境界/属性/给装备/清用户忙碌状态，但**没有**“直接让玩家领悟指定功法”的命令；GM 权限依赖 `GM_ADMINS` 配置。
- 战斗引擎日志包含可断言的文本：战斗开始属性行、`触发【技能名】…`、`施展大招【…】`、`被眩晕`、`恢复`、`侵蚀`、`消散`、`反击`、`庇护` 等。
- 已发现一个待确认的功能性 Bug 迹象：`handlers/combat_handlers.py` 的 `handle_spar` 在写回 `result` 前即使用 `result[...]`，疑似缺少 `player_vs_player(...)` 调用；功能测试将把它作为首个实战验证点。

## Goals / Non-Goals

**Goals:**
- 建立项目内统一测试资产目录与命名规范，让用例与结果可版本化、可浏览。
- 提供脚本化流程：用例同步到平台、跑一批域用例、结果导出到 `functional_tests/results/<日期>_<目标>/`。
- 编写第一批功能回归用例；设计并执行玩家互相战斗用例，验证 content-design 中的心法被动、武器/功法触发技、大招、持续状态效果。
- 输出测试平台能力差距报告，区分“平台已支持可立即测/部分支持/不支持需增强”。
- 所有可测项先跑一轮，结果归档；发现的功能 Bug 用 bd 记录，不在本变更修游戏代码。

**Non-Goals:**
- 不修改游戏插件运行时代码、配置、数据库结构、`metadata.yaml`。
- 不实现测试平台本身的功能增强（如 RNG seed、时间加速、导出 API）；这些只写进差距报告和 bd/任务建议。
- 不追求随机触发效果的 100% 单次确定性通过；采用重复运行 + 证据聚合的方式验证。

## Decisions

### D1: 测试资产目录结构
仓库根新增 `functional_tests/`：

```
functional_tests/
├── README.md                     # 目录规范、命名、使用流程
├── platform-gap-report.md        # 测试平台能力差距报告（本变更交付物）
├── cases/                        # 用例源文件（source-of-truth，可分子目录）
│   ├── player/                   # 玩家/修炼/突破
│   ├── economy/                  # 装备/丹药/商店/储物戒/银行/悬赏
│   ├── pve/                      # Boss/历练/秘境
│   ├── social/                   # 宗门/双修/洞天/灵田/灵眼
│   ├── pvp/                      # 切磋/决斗/传承PK/效果验证
│   └── gm/                       # GM 工具
└── results/
    └── <YYYY-MM-DD>_<target>/    # 每次测试目标一个目录
        ├── summary.md            # 运行概览：通过/失败/跳过/遗留问题
        ├── cases/                # 每用例 result JSON（含步骤结果）
        └── messages/             # 每用例运行期消息轨迹导出（可选）
```

命名规则：`results` 子目录固定 `日期_目标`（目标用短横线小写英文，如 `2026-08-17_pvp-effects`、`2026-08-17_core-smoke`）。

### D2: 用例源文件分层 + 同步时拍平
平台加载器只读顶层 `*.json`，因此：
- 源文件可放在 `functional_tests/cases/<domain>/<name>.json` 便于分类；
- 同步脚本把全部 `*.json` 复制到平台数据目录 `cases/` **顶层**，文件名即用例名；
- 同步时校验：所有用例 `name` 全局唯一；非法用例拒绝复制并报错；
- 用例 JSON 兼容测试平台 `loader.validate_case` 格式，保留必填 `description`/`scenario` 和步骤 `note`。

### D3: 测试套件控制脚本 `scripts/test_suite_ctl.py`
用 Python 标准库 `urllib`（与平台 CLI 一致）封装：
- `sync-cases`：扫描 → 校验 → 拍平复制到平台 cases 目录；
- `run --tag <tag> [--repeat N]`：调平台 REST 启动用例，轮询终态；`--repeat` 供随机效果用例循环运行；
- `export --target <target> [--date]`：按最近运行记录拉取 `runs show` 明细，写入 `functional_tests/results/<date>_<target>/`；
- `fixture --profile pvp`：为 PvP 固定身份玩家准备基线（见 D5）。
脚本只读写本项目测试资产与平台 via REST；直接操作修仙插件数据库仅限 fixture 场景（见 D5）。

### D4: PvP 用例的固定身份与会话设计
所有 PvP 用例使用群聊 `conversation.kind = "group"`、固定的 `group_id`（如 `webtest_pvp_001`）和 `pin_players`：

```json
"conversation": {
  "kind": "group",
  "group_id": "webtest_pvp_001",
  "pin_players": { "gm": "900000001", "p1": "900000002", "p2": "900000003" }
}
```

- 若白名单非空，需把 `group_id` 加入测试实例的 `WHITELIST_GROUPS`；
- GM 身份用于 `修仙GM 设置境界/设置攻击/给予装备` 等准备步骤；需要该 ID 在测试实例 `GM_ADMINS` 中；
- 玩家 ID 固定为数字，使 `切磋 <id>`/`决斗 <id>` 可被目标解析识别。

### D5: PvP 效果验证的 fixture 与随机效果处理
由于平台/现有 GM 不能直接“领悟指定功法”，战斗效果验证分两层：
- **纯平台可测**：心法被动（装备 `main_technique`）、武器触发技（装备带 `trigger_skills` 的武器）——用 GM 给物品 + 玩家「装备」即可装配，完全走平台消息验证。
- **fixture 辅助可测**：功法触发技/大招需要 `player_skills` 记录。`test_suite_ctl.py fixture --profile pvp` 在专用测试实例中直接向插件数据库写入固定测试 ID 的 `player_skills` 行（并重置属性/冷却/忙碌状态），随后用例内通过真实指令「激活功法 <名>」完成装配；战斗仍在平台真实管线中验证。
- 随机触发验证：单次战斗可能不触发，脚本层面支持 `--repeat` 对同一效果循环执行 N 次，每轮前重置冷却；聚合多次战斗日志中出现目标效果文本的次数/证据，写入结果 summary 并标记“验证强度（抽样）”。
- 大招解锁门槛（`min_action_index`、血量阈值）用 GM 设低攻/高血构造长战斗，断言日志出现「施展大招」。

### D6: 第一批用例范围
第一批按“当前平台能稳定支撑 + fixture 可补强”优先：
- `player-lifecycle`（私聊）：我要修仙→选择灵修→我的信息→开始闭关→忙碌拦截→出关；
- `equipment-heart-weapon`（群聊/私聊）：GM 固定身份给装备→装备→我的装备→卸下；
- `pvp-basic-duel`（群聊固定身份）：双玩家创建→GM 设属性→决斗→断言战斗开始/胜利/回合；
- `pvp-heart-passive`：装备不同心法后决斗，断言战斗首行属性（如伤害/气血）随被动变化；
- `pvp-weapon-trigger`：装备带触发技武器（如青云天剑/混元至宝鼎/弑龙帝枪），重复运行断言「触发【…】」；
- `pvp-technique-effects`（fixture 辅助）：**一次性覆盖 14 族效果键**——damage_bonus/combo/stun/counter/damage_reduction/heal/vampire/dot/buff/debuff/unavoidable/pierce/reflect/survive，外加 fatigue 单独用例；使用对应验证/正式技能（回春诀、噬血剑意、蚀骨咒、燃血诀、破风剑意、涅槃诀、铁棘功等），断言各自日志特征；
- `pvp-ultimate-*`：伤害大招（万剑归宗）、治疗大招（回天圣手）、持续 DOT 大招（九幽噬魂咒）、免死大招（涅槃诀）与解锁门槛；
- `gm-basics`：GM 设境界/属性/给装备/清CD；
- `bank-sect-smoke` 等非战斗域基础路径。

### D7: 平台能力差距报告
报告按以下维度分类：
- **Supported**：消息注入/群聊多玩家/固定身份/expect 匹配/轨迹/标签/批注/自定义会话；
- **Partially supported**：随机战斗效果验证（能看日志但无法 seed/保证触发）、GM 前置（需手动配 `GM_ADMINS`/白名单）、长定时任务（真实 sleep 太慢，部分可 GM 强制结算）；
- **Unsupported**：直接授予已领悟功法（无 GM 命令/API）、结构化 `@` 消息段注入、直接数据库状态断言、时间加速、批量结果导出到项目目录（当前需自建脚本）、确定性 RNG 种子。
每条给出原因与建议增强（如 GM 增加“给予已领悟功法”、平台增加 `At` 消息段构造、`/api/runs` 导出接口、RNG seed 配置等）。

## Risks / Trade-offs

- [直接写插件数据库做 fixture 可能污染正式数据] → 只允许固定测试 ID；官方建议用独立测试 AstrBot 数据目录；脚本操作前备份或仅对 `pin_players` 声明的 ID 生效。
- [随机触发导致个例失败] → 引入 `--repeat` 聚合，结果不把单次抽样当确定性通过；报告明确“抽样验证”。
- [用例源分层与平台顶层加载不一致] → 同步脚本强制拍平 + 全局唯一名校验；README 写明“平台侧始终是拍平后的副本”。
- [`handle_spar` 疑似 bug 会让切磋用例失败] → 第一批先以 `决斗` 跑战斗效果；`spar` 用例保留并标记“预期失败/待修复”，失败会形成 bug 证据。
- [结果目录可能被人为覆盖] → `export` 若目标目录已存在则生成 `_2`/时间戳后缀，不覆盖历史。

## Migration Plan

1. 新增 `functional_tests/` 目录结构与 README、gap-report。
2. 新增 `scripts/test_suite_ctl.py`（sync/run/export/fixture）。
3. 更新 `AGENTS.md` 与 `design_docs/README.md`。
4. 编写第一批用例，运行可测项，导出结果。
5. 为 gap/发现 bug 创建 bd issue；提交并推送。

## Resolved Decisions

- **用户已确认允许 fixture 脚本写测试库**：`test_suite_ctl.py fixture --profile pvp` 可向专用测试实例的插件数据库直接写入固定测试 ID 的 `player_skills`/属性/冷却数据；仅限固定测试 ID，并建议独立测试实例。
- **用户已确认第一批做全 14 族效果矩阵**：首轮即覆盖全部效果键与大招类型，重复运行聚合抽样证据。