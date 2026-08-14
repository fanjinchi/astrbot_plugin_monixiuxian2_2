"""AstrBot 插件入口：网页端测试平台（webtest 平台适配器 + Web 服务 + 测试用例引擎）。

插件加载时（本文件被 import）即完成平台适配器注册——AstrBot 的 Dashboard
平台管理页会出现「网页测试平台 (webtest)」平台，启用后 run() 启动 Web 服务。
数据与运行时状态全部存放在 data/plugin_data/astrbot_plugin_testplatform/ 下。

Command 「-」- 无指令路由；本插件通过平台适配器接入消息管线，无独立指令。
"""

import os
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Star, StarTools

# 必须在模块顶层 import 以触发适配器注册（热重载/启用时均生效）
from .adapter import webtest_adapter  # noqa: F401
from .server.app_state import app_state


class TestPlatformPlugin(Star):
    """网页端测试平台插件。

    负责初始化数据目录与全局状态；平台适配器与 Web 服务生命周期由 AstrBot
    平台管理器管理（启用 webtest 平台时启动，禁用/热重载时注销）。
    """

    def __init__(self, context, config) -> None:
        super().__init__(context)
        self.config = config
        data_dir = Path(StarTools.get_data_dir("astrbot_plugin_testplatform"))
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("WEBTEST_PLUGIN_DATA_DIR", str(data_dir))
        app_state.setup(plugin_config=config, data_dir=data_dir)
        logger.info("【测试平台】插件初始化完成，数据目录: %s", data_dir)

    async def initialize(self) -> None:
        """AstrBot 加载完成后调用：初始化数据库。"""
        try:
            await app_state.ensure_db()
            logger.info("【测试平台】数据库就绪")
        except Exception as exc:  # 初始化失败不阻断插件加载
            logger.error(f"【测试平台】数据库初始化失败: {exc}")
