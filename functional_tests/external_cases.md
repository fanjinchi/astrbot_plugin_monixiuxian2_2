# 外部用例登记（不属于本插件的用例）

本仓 `functional_tests/cases/` 只放**本插件**的用例源；平台运行时用例目录
`data/plugin_data/astrbot_plugin_testplatform/cases/` 是**跨插件共享**目录，
自 2026-09-12 起按归属插件分子目录（`cases/<插件目录名>/`，子目录名即归属，
平台 loader 强制校验用例 JSON 的 `owner` 与子目录一致）。

**平台目录的归属已由子目录自描述，`sync-cases` 也只扫描/只写本插件的
`cases/astrbot_plugin_monixiuxian2_2/` 子目录**——别家插件的用例位于其自己的子目录，
不会再触发「未纳管」告警，也无需再登记到本表。本表保留为历史事故档案。

| 用例名 | 归属插件 | 源路径（相对 `data/plugins/`） | 平台副本位置 | 同步方式 |
|---|---|---|---|---|
| `tarot-commands-smoke` | `astrbot_plugin_tarot` | data/plugins/astrbot_plugin_tarot/functional_tests/cases/tarot/tarot-commands-smoke.json | `cases/astrbot_plugin_tarot/` | 人工拷贝（tarot 仓暂无同步脚本） |
| | | 说明：2026-08-28 merge-tarot-reading-into-divination 的宿主侧回归防线（归档 tasks.md:13，runs 5/5）；2026-09-12 从本仓 cases/misc/ 归位到 tarot 仓，平台副本同日迁入 tarot 的 owner 子目录。 | | |
| `smoke-test` | `astrbot_plugin_testplatform` | （无 —— 平台 cases/loader.py 的「新建用例」空白模板被误存成用例文件） | 已删除 | - |
| | | 说明：2026-09-12 两份副本（本仓源 + 平台数据目录）均已删除；平台「新建用例」仍由 loader 模板即时生成（需带 owner），不受影响。 | | |

维护约定：

- 别家插件的用例要改，去**归属插件的仓库**改，再按其同步方式更新平台副本；不要动本仓 `cases/`，也不要动平台目录里别家的子目录。
- `sync-cases` 的「未纳管用例」告警只针对本插件子目录：要么回填进本仓
  `functional_tests/cases/<domain>/`（含 `"owner": "astrbot_plugin_monixiuxian2_2"`），要么确认废弃后手工删平台副本。
