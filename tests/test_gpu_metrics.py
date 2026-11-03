"""GPU 指标采集的测试：解析 CSV 与统计逻辑（不启动 PowerShell）。"""

import shutil
import uuid
from pathlib import Path

from tools.gpu_metrics import _percentile, read_engine_csv

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_csv(lines):
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex / "engine.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return path


def test_read_engine_csv_basic():
    path = make_csv([
        "10:00:00.000,50.0,0.0,1.0,0.0,0.0",
        "10:00:00.200,90.0,0.0,2.0,0.0,0.0",
        "10:00:00.400,95.0,0.0,0.0,0.0,0.0",
    ])

    try:
        stats = read_engine_csv(path)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)

    assert stats["samples"] == 3
    assert stats["3d"]["max"] == 95.0
    assert stats["3d"]["mean"] == round((50 + 90 + 95) / 3, 1)
    assert stats["copy"]["max"] == 2.0
    # 三点里只有两点 >= 80%
    assert stats["3d"]["over_80_pct"] == round(2 / 3 * 100, 1)


def test_read_engine_csv_skips_bad_lines():
    path = make_csv([
        "10:00:00.000,50.0,0.0,1.0,0.0,0.0",
        "garbage line",
        "10:00:00.400,abc,0.0,0.0,0.0,0.0",
        "10:00:00.600,70.0,0.0,0.0,0.0,0.0",
    ])

    try:
        stats = read_engine_csv(path)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)

    assert stats["samples"] == 2
    assert stats["3d"]["max"] == 70.0


def test_read_engine_csv_missing_file():
    assert read_engine_csv(REPO_ROOT / ".test_tmp" / "definitely_missing.csv") == {}


def test_percentile():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    assert _percentile(values, 0) == 1
    assert _percentile(values, 50) == 6
    assert _percentile(values, 100) == 10
    assert _percentile([], 90) is None
