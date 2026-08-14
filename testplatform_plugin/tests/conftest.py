"""pytest 公共配置：把仓库根加入 sys.path，使测试可 import testplatform_plugin 包。"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
