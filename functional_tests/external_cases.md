# 外部用例登记（不属于本插件的用例）

本仓 `functional_tests/cases/` 只放**本插件**的用例源；平台运行时用例目录
`data/plugin_data/astrbot_plugin_testplatform/cases/` 是**跨插件共享**的拍平副本，
因此会同时装着别的插件的用例。凡归别人管的用例一律登记在此，避免再次被回填进本仓。

| 用例名 | 归属插件 | 源路径（相对 `data/plugins/`） | 平台目录有副本 | 同步方式 |
|---|---|---|---|---|
| `tarot-commands-smoke` | `astrbot_plugin_tarot` | data/plugins/astrbot_plugin_tarot/functional_tests/cases/tarot/tarot-commands-smoke.json | 是 | 人工拷贝（tarot 仓暂无同步脚本） |
| | | 说明：2026-08-28 merge-tarot-reading-into-divination 的宿主侧回归防线（归档 tasks.md:13，runs 5/5）；2026-09-12 从本仓 cases/misc/ 归位到 tarot 仓。平台数据目录那份副本保留以维持可跑状态，但它与本仓源无关 —— sync-cases 会把它报成「未纳管」，属预期告警。 | | |
| `smoke-test` | `astrbot_plugin_testplatform` | （无 —— 平台 cases/loader.py:72 的「新建用例」空白模板被误存成用例文件） | 否 | - |
| | | 说明：2026-09-12 两份副本（本仓源 + 平台数据目录）均已删除；平台「新建用例」仍由 loader 模板即时生成，不受影响。 | | |

维护约定：

- 新登记的用例若要改，去**归属插件的仓库**改，再按其同步方式更新平台副本；不要动本仓 `cases/`。
- `scripts/test_suite_ctl.py sync-cases` 的「未纳管用例」告警列出上表之外的平台文件：
  要么回填进本仓（若确属本插件），要么登记到本表（若属别的插件）。
