"""进度回调的测试（自我对弈与导出）。

这两个回调是速度测试工具（tools/speed_test.py）的基础：
它们让长任务可以边跑边汇报进度与速度。
"""

import shutil
import uuid
from pathlib import Path

import pytest

from training import export_dataset, self_play

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_self_play_progress_callback(workdir):
    """run_self_play 必须在每局结束后回调一次进度。"""
    seen = []

    self_play.run_self_play(
        games=2,
        seats=("heuristic", "heuristic", "heuristic", "heuristic"),
        seed_start=930000,
        checkpoint=None,
        out_path=workdir / "progress.jsonl",
        verbose=False,
        progress=lambda done, total, decisions: seen.append((done, total, decisions)),
    )

    assert len(seen) == 2
    assert seen[0][0] == 1 and seen[0][1] == 2
    assert seen[-1][0] == 2 and seen[-1][2] > 0


def test_export_progress_callback(workdir):
    """export 必须在结束时回调一次进度（每 10 局或最后一局）。"""
    source = workdir / "export_progress.jsonl"
    seen = []

    self_play.run_self_play(
        games=2,
        seats=("heuristic", "heuristic", "heuristic", "heuristic"),
        seed_start=931000,
        checkpoint=None,
        out_path=source,
        verbose=False,
    )

    export_dataset.export(
        source,
        out_path=workdir / "export_progress.npz",
        progress=lambda done, total, samples: seen.append((done, total, samples)),
    )

    assert seen, "导出没有回调进度"
    assert seen[-1][0] == seen[-1][1] == 2
    assert seen[-1][2] > 0
