# 功能测试套件（Functional Test Suite）

本目录是本仓库**功能测试用例与测试结果的唯一归档地**。用例以 JSON 形式存放在 `cases/`，运行时通过网页端测试平台执行，结果按日期与测试目标归档到 `results/`。

## 目录规范

```
functional_tests/
├── README.md                     # 本文档：目录规范、命名、使用流程
├── platform-gap-report.md        # 测试平台能力差距报告（Supported / Partially / Unsupported）
├── cases/                        # 用例源文件（source-of-truth，可按功能域分子目录）
│   ├── player/                   # 玩家创建、修炼、突破
│   ├── equipment/                # 装备、武器、心法
│   ├── economy/                  # 丹药、商店、储物戒、银行、悬赏
│   ├── pve/                      # Boss、历练、秘境
│   ├── sect/                     # 宗门（默认宗门/建设/师承/晋升/出师回收/指令统一/悬赏分流/商店/事件标记）
│   ├── social/                   # 双修、洞天、灵田、灵眼（宗门已独立到 sect/）
│   ├── pvp/                      # 切磋、决斗、传承PK、效果验证
│   └── gm/                       # GM 工具
└── results/
    └── <YYYY-MM-DD>_<target>/    # 每次测试目标一个目录
        ├── summary.md            # 运行概览：通过/失败/跳过/遗留问题
        ├── cases/                # 每用例结果 JSON（含步骤结果）
        └── messages/             # 每用例运行期消息轨迹导出（可选）
```

### 目录命名规则

- `cases/` 下按功能域分子目录，文件名即用例名，例如 `pvp/pvp-effect-stun.json`。
- `results/` 子目录固定为 `<YYYY-MM-DD>_<target>`：
  - `<YYYY-MM-DD>`：本地运行日期，例如 `2026-08-17`；
  - `<target>`：短横线小写英文的测试目标名，例如 `core-smoke`、`pvp-effects`；
  - 示例：`results/2026-08-17_core-smoke/`。
- `export` 若目标目录已存在，会自动生成 `_2`/时间戳后缀，**不覆盖历史结果**。
- one-shot `run --export <dir>` 直接落盘机器可读 `summary.json`（`total`/`passed`/`failed`/`errors`/`runs`），供 CI 或脚本消费。

## 用例 JSON 编写约定

用例必须兼容测试平台的 `loader.validate_case` 格式，并满足以下约定：

- `name` 必须与文件名一致，且在整个套件中**全局唯一**。
- 必填字段：`name`、`description`、`scenario`、`steps`。
- 步骤类型为 `type` 字段：
  - `send`：发给测试会话的消息（触发真实 AstrBot 管线），必填 `player`/`text`；
  - `expect`：断言，`expect.match` 支持 `re:` 前缀（正则），否则按子串匹配，必填 `timeout`；
  - `expect_not`：负向断言，窗口内任何回复命中 `match` 即失败并记录违规消息（v0.2.0）；
  - `sleep`：等待秒数，必填 `seconds`。
- 用例顶层可声明 `deterministic: true` + `seed`（整数，默认 42）：每个 `send` 注入前重置全局随机种子，尽力让概率型行为（随机效果、悬赏/事件池）可复现；不要用 `--repeat` 当“多抽一次”的手段（见下条种子告警）。注意：平台的 `random.seed()` 不区分轮次（`cases/runner.py` 每轮同种子），想真正换抽样请用 `--fixture` 驱动的变体或不同战斗长度，而不是靠 `--repeat` 重复同一随机序列。
- `expect`/`expect_not` 步骤可带 `combine: true`：把窗口内全部回复按换行拼接后再匹配（跨条断言）。
- 用例顶层可声明 `pre_run_hook`（对象 `{"command": "<shell>", "timeout": 60}`，`timeout` 可选正数秒、默认 60）：每次运行（含 `--repeat` 每轮）首个步骤前由平台服务端执行该 shell 命令并注入 `WEBTEST_CASE_NAME`/`WEBTEST_RUN_INDEX`/`WEBTEST_CONVERSATION_ID`/`WEBTEST_PLAYERS`（JSON：player 标签→实际 user_id）环境变量，用于复位被测插件持久基线。宗门域用例已全部内嵌该钩子（command 调 `scripts/test_suite_ctl.py fixture --profile sect --yes`），`run --tag sect` 无需再带 `--fixture`（该参数保留兼容）。
- `conversation.kind`：`private` 或 `group`；群聊用例可带固定 `group_id` 与 `pin_players`。
- 群聊用例的每个 `send` 文本必须以 AstrBot 全局 `wake_prefix`（当前为 `#`）开头，例如 `#我要修仙 灵修`；否则群消息不会唤醒插件 Filter。
- PvP 用例固定身份约定：
  - 群聊 `group_id` 使用 `webtest_pvp_001`；
  - `pin_players` 固定：`gm=900000001`、`p1=900000002`、`p2=900000003`；
  - 若测试实例开了白名单，需把该群加入 `WHITELIST_GROUPS`；GM 命令需要 `900000001` 在 `GM_ADMINS`。
- 身份派生与隔离（v0.3.0）：`pin_players` 值可为对象 `{"user_id": "...", "isolate": true}`（可再带 `fresh: true`）派生隔离身份——派生身份与被测插件中按 `user_id` 精确匹配的特权（如 `GM_ADMINS`）不再匹配，需要 GM 指令的用例必须保留固定 pin 并配合 `pre_run_hook` 复位基线。
- **断言锚点原则（2026-09-11 flavor-copy-assembly 复盘后新增，强制）**：文案变体会随内容导入整段改写，断言只能锚**代码侧不变量**：
  - 代码插值进文案的**值**：`【技能名/效果名/境界名】`、`… 点伤害`、`再败 N 回`（变体怎么写，变量都得出现）；
  - 代码拼装的结构行：`-- 第 N 回合 --`（`round_header` 单源 str）、对战面板首行 `名字：气血 N/M，伤害 X，身法 Y，迅捷 Z`（`managers/combat_manager.py:247-253`）、GM 回执全串（数值带千分位，如 `999,999`）；
  - route B 双槽结构用 `re:[^\n]\n<面板首行>` 断“flavor 段存在且面板紧随其后”，不锚文学句；
  - **每个 `send` 只配一个断言**：平台 `cases/runner.py` 只在**新回复到达时**求值，串接的第二个 expect 永远等不到新消息而超时；跨条断言靠 `combine: true` 拼窗口；
  - 负向守护（未渲染占位符、独占一行的 `---`）同样要 `combine: true`（扫全窗口），且**前面必须再发一条哨兵 `send`**（如 `#我的信息`）——否则无新回复、守护永不求值=假通过；
  - 禁止 `re:<目标>|战斗开始` 这类恒真兼底分支：它把断言变成摆设（历史教训：bd -khh）；
  - 确实无名字变量的场景（`lifesteal`/`reflect`/`dodge`/`battle_victory` 等）只能锚文案时，取该场景**全部变体**的稳定子串并集，并在 `note` 注明“文案再改需同步此处”；
  - GM 破坏性子命令（`时间快进`/`清除CD`/`清除全部冷却`）必须带 `确认` 尾参，且该 `send` 的 `player` 必须是 `gm`（900000001），否则只会收到 `❌ 你没有权限使用修仙GM命令！`。
- **概率效果口径**：不再靠 `--repeat` 兜底——把战斗拉长（双方 `气血 8000`；境界悬殊的武器用例用 `999999999`，由 `combat.action_limit=200` 封顶）使 8%~25% 触发率单场必中，断言直接锚效果行（效果类实测 67~76 回合）。真抽样型覆盖（突破领悟、机缘掉落、闭关悟道、走火入魔/回生丹）不写进断言，由 `scripts/test_suite_ctl.py` 的 `EFFECT_EVIDENCE_PATTERNS` 证据计数，在归档 summary 的「效果证据聚合」里体现；但 `--repeat` 不能换抽样（平台每轮同种子），要拿到真实样本得换种子或补 `tests/` 单测断言渲染后的变体集合。
- **fixture profile 清单**（`fixture --profile <p> --yes`，均由用例 `pre_run_hook` 自带）：`pvp`（3 个固定 ID 的属性/技能位/冷却）、`sect`（宗门基线 + 商店种子）、`breakthrough`（练气九阶 + 修为 999,999 + `level_up_rate=-100` → 最终成功率 0.0% 必败；加 `--breakthrough-streak 19` 则触发连败保底强制成功）。三个 profile 每次都会先清理测试平台派生的 `case_%` 虚拟玩家，避免污染 `时间快进` 的全局计数（bd -777）；因此任何用例都不得断言该计数等于具体值，应用 `[1-9]\d* 条` 断“确实被前移”。
- 域 tag `narrative-flavor` = 叙事文案（route A/B）回归集，一条命令跑全：`run --tag narrative-flavor`。
- 每个用例至少有一个功能域 `tag`（如 `player`、`equipment`、`pvp`、`pve`、`gm`、`economy`、`sect`、`social`），便于 `run-all --tag <tag>` 定向回归。
- 随机/概率效果用例在 `description` 或 `scenario` 中写明证据口径（单场拉长 / 结构性断言 / 交 `tests/`）；需要聚合「效果证据」时得用**不同种子或不同用例**的多次跑批，`--repeat` 本身不换抽样（见上文确定性段落）。
- 触发率断言必须附带实测依据：战报长度取 `第 N 回合` 最大值，归档 summary 的「效果证据聚合」行会输出 `最长回合=N`。实测参考（2026-09-11，气血 8000）：被动/触发类效果单场 67~76 回合，大招类 33~90，`action_limit=200` 封顶时 100；按 60 次出手保守估算，10% 触发率整场不触发的概率约 2e-3，所以单场断言可代替抽样。若日后把气血调低使战斗短于 ~45 回合，这些断言必须改回抽样口径。
- 锚定文案变体（prose）的断言必须在 `note` 里写明 `文案再改需同步此处（<domain.scene>）`，且同步面 = 用例断言 + `EFFECT_EVIDENCE_PATTERNS` 两处，缺一不可。
- 同库禁止并发跑批：多个 `run`/`--repeat` 进程共享同一组固定测试 ID 与 `.fixture-backup.json`，并发会互相覆盖基线、使“单场必中”类断言失真。需要并行请各起一份独立 `xiuxian_data_lite.db` 副本与独立平台会话。
- 用例里的 `测试玩家1`/`测试玩家2`/`测试GM` 是 fixture 写死的名字表（`scripts/test_suite_ctl.py` 的 `names`），不是平台 sender 标签；改这些名字会同时弄坏所有GM 回执与战报面板断言。

## 同步 / 运行 / 导出流程

所有操作通过 `scripts/test_suite_ctl.py` 完成（复用测试平台 REST，标准库实现，不新增依赖）。

```bash
# 0. 准备环境（与平台 CLI 一致）
export WEBTEST_URL=http://127.0.0.1:8765
export WEBTEST_TOKEN=<token>

# 1. 同步用例：扫描 functional_tests/cases/**/*.json → 校验 → 拍平复制到平台 cases 顶层
#    sync-cases 只写用例 JSON，不向平台 cases 目录写入 *.meta.json（历史残留会自动清理）
uv run python scripts/test_suite_ctl.py sync-cases

# 2. 按标签运行（例如所有 PvP 用例；重复 3 次用于随机效果聚合）
#    随机效果用例可加 --fixture --db <测试库>：每轮前重置固定测试玩家/冷却
#    （平台 v0.3.0 起宗门用例已内嵌 pre_run_hook 自动复位：run --tag sect 无需 --fixture，该参数保留兼容）
uv run python scripts/test_suite_ctl.py run --tag pvp --fixture --db /path/to/xiuxian_data_lite.db
uv run python scripts/test_suite_ctl.py run --tag player

# 3. 导出最近运行结果到 results/<日期>_<目标>/
uv run python scripts/test_suite_ctl.py export --target pvp-effects
uv run python scripts/test_suite_ctl.py export --target core-smoke --date 2026-08-17

# 4. （兼容保留）PvP 效果测试前准备固定身份玩家（写专用测试实例数据库，仅限固定测试 ID）
#    ⚠ 仅应在独立测试 AstrBot 数据目录/实例上执行
#    宗门域已由用例内 pre_run_hook 调用（fixture --profile sect --yes），无需外部执行本命令
uv run python scripts/test_suite_ctl.py fixture --profile pvp
```

### One-shot 编排（v0.2.0，推荐单命令方式）

`run` 支持透传平台 one-shot 参数：`--sync`（跑前同步）、`--reload <plugin>`（跑前热重载被测插件）、`--export <dir>`（结果落盘，写每个 run 的 JSON + 机器可读 `summary.json`）、`--quiet`（仅输出汇总）：

```bash
# 同步 + 热重载被测插件 + 跑 pvp 域 + 结果落盘 summary.json（plugin 名用平台注册名，非仓库名）
uv run python scripts/test_suite_ctl.py run --tag pvp --sync \
  --reload astrbot_plugin_monixiuxian2_2 --export /tmp/pvp-out --quiet
# 然后按既有流程归档为 date_target 目录：
uv run python scripts/test_suite_ctl.py export --target pvp-effects
```

也直接支持平台原始 CLI（见仓库根 `AGENTS.md`）：

```bash
CLI=~/code/AstrBot/data/plugins/astrbot_plugin_testplatform/scripts/test_platform_cli.py
uv run python $CLI case run <case>
uv run python $CLI case run-all --tag <tag> --sync-from <dir> --reload <plugin> --export <dir>
uv run python $CLI case check --source <flat_dir>   # 源与平台副本语义比对（注意：非递归 *.json，源须为拍平目录）
```

> 平台 CLI 的 `--sync-from`/`check --source` 使用**非递归** `*.json` glob，只能处理拍平目录；`functional_tests/cases/` 下的源用例是分域子目录，因此**同步必须走 `scripts/test_suite_ctl.py sync-cases`**（递归扫描+拍平），`--reload` 的插件名为平台注册名 `astrbot_plugin_monixiuxian2_2`。

## 结果归档约定

- 每次“测试目标”的运行结果导出到一个新目录 `results/<YYYY-MM-DD>_<target>/`；
- `summary.md` 统计通过/失败/不稳定/跳过，并列出遗留问题与证据路径；
- `cases/` 保存每个用例的 result JSON（步骤级结果）；
- `messages/` 保存消息轨迹（可选）；
- 发现的功能 Bug 登记到 `bd` issue（不使用 Markdown TODO），并在 `summary.md` 或 `platform-gap-report.md` 中链接证据。

## 维护责任

- 新增/修改游戏玩法后，若涉及可观测行为，应在本目录新增或更新用例，并在 `AGENTS.md` 的“功能测试套件”流程中执行同步与回归。
- 玩法或设计变更仍须同步 `design_docs/`（见根目录 `AGENTS.md` §14）。