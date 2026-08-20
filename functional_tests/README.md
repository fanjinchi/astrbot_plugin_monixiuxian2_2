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
│   ├── social/                   # 宗门、双修、洞天、灵田、灵眼
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
- 用例顶层可声明 `deterministic: true` + `seed`（整数，默认 42）：每个 `send` 注入前重置全局随机种子，尽力让概率型行为（随机效果、悬赏/事件池）可复现；必要时配合 `--repeat N` 采样兑底。
- `expect`/`expect_not` 步骤可带 `combine: true`：把窗口内全部回复按换行拼接后再匹配（跨条断言）。
- `conversation.kind`：`private` 或 `group`；群聊用例可带固定 `group_id` 与 `pin_players`。
- 群聊用例的每个 `send` 文本必须以 AstrBot 全局 `wake_prefix`（当前为 `#`）开头，例如 `#我要修仙 灵修`；否则群消息不会唤醒插件 Filter。
- PvP 用例固定身份约定：
  - 群聊 `group_id` 使用 `webtest_pvp_001`；
  - `pin_players` 固定：`gm=900000001`、`p1=900000002`、`p2=900000003`；
  - 若测试实例开了白名单，需把该群加入 `WHITELIST_GROUPS`；GM 命令需要 `900000001` 在 `GM_ADMINS`。
- 每个用例至少有一个功能域 `tag`（如 `player`、`equipment`、`pvp`、`pve`、`gm`、`economy`、`social`），便于 `run-all --tag <tag>` 定向回归。
- 随机/概率效果用例在 `description` 或 `scenario` 中写明“抽样验证”，并配合 `--repeat N` 聚合证据。

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
#    随机效果用例建议加 --fixture --db <测试库>：每轮前重置固定测试玩家/冷却
uv run python scripts/test_suite_ctl.py run --tag pvp --repeat 3 --fixture --db /path/to/xiuxian_data_lite.db
uv run python scripts/test_suite_ctl.py run --tag player

# 3. 导出最近运行结果到 results/<日期>_<目标>/
uv run python scripts/test_suite_ctl.py export --target pvp-effects
uv run python scripts/test_suite_ctl.py export --target core-smoke --date 2026-08-17

# 4. PvP 效果测试前准备固定身份玩家（写专用测试实例数据库，仅限固定测试 ID）
#    ⚠ 仅应在独立测试 AstrBot 数据目录/实例上执行
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