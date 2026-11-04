"""pytest 的公共夹具。

注意：不要用 `tmp_path` —— 这台机器的系统 TEMP 在沙箱里不可写，
pytest 建临时目录会直接 PermissionError。统一用仓库内的 `.test_tmp`。
"""

import shutil
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    """仓库内的临时目录，用完自动删。"""
    path = ROOT / ".test_tmp" / f"t_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
