"""Guard tests for version fields that must stay in sync.

``metadata.yaml`` is the version AstrBot reads; the README version line and the
newest changelog entry are the human-facing copies. They drifted apart for three
versions (README stayed at v3.15.0 up to v3.17.1), so keep them pinned here.
"""

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_readme_and_changelog_match_metadata_version():
    """metadata.yaml, the README version line and the top changelog entry agree."""
    metadata = (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)", metadata, re.MULTILINE)
    assert match, "metadata.yaml 缺少 version 字段"
    version = match.group(1)

    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"^> \*\*版本:\*\*\s*(\S+)", readme, re.MULTILINE)
    assert match, "README.md 缺少「> **版本:**」行"
    assert match.group(1) == version, "README 版本行与 metadata.yaml 不一致"

    match = re.search(r"^### (v\d+\.\d+\.\d+) - ", readme, re.MULTILINE)
    assert match, "README.md 更新日志缺少版本标题"
    assert match.group(1) == version, "README 更新日志首条与 metadata.yaml 不一致"
