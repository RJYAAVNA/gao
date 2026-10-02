"""契约测试占位文件。

S3 阶段采集器的契约测试将在此添加，
该文件确保 CI 中 pytest 收集阶段不会因目录为空而失败。
"""

import pytest


def test_placeholder() -> None:
    """占位测试，确保测试套件可以运行。"""
    assert True


@pytest.mark.skip(reason="S3 阶段暂无契约测试")
def test_contract_placeholder() -> None:
    """未来的契约测试在此添加。"""
    pass
