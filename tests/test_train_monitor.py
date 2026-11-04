"""训练进度网页的测试：进度文件读写、失败标记、HTTP 接口。

这些测试**不需要 torch**——进度快照和网页服务都是纯标准库，
所以没装 torch 的机器上也能跑。
"""

import json
import shutil
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from training.progress import ProgressWriter, mark_failed, read_progress
from tools.train_monitor import make_server

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_progress_writer_records_epochs(workdir):
    target = workdir / "progress.json"

    writer = ProgressWriter(target, epochs_total=2, data="x.npz", device="cpu",
                            batch_size=64, lr=1e-3, min_interval=0.0)
    writer.start(batches_per_epoch=4, train_samples=100, val_samples=20)

    writer.batch(1, 2, loss=1.5)
    writer.epoch_end({
        "epoch": 1,
        "train_loss": 1.4,
        "train_acc": 0.7,
        "val_loss": 1.2,
        "val_acc": 0.72,
        "val_group_acc": 0.75,
        "seconds": 3.0,
    })

    snapshot = read_progress(target)

    assert snapshot["status"] == "running"
    assert snapshot["epoch"] == 1
    assert snapshot["batches_per_epoch"] == 4
    assert snapshot["progress"] == pytest.approx(0.5, abs=1e-6)
    assert snapshot["history"][0]["val_acc"] == 0.72
    assert snapshot["best_val_acc"] == 0.72
    assert snapshot["best_epoch"] == 1


def test_progress_writer_finish_and_best(workdir):
    target = workdir / "progress.json"

    writer = ProgressWriter(target, epochs_total=2, min_interval=0.0)
    writer.start(batches_per_epoch=3)

    writer.epoch_end({"epoch": 1, "val_acc": 0.60, "train_loss": 1.5, "train_acc": 0.5})
    writer.epoch_end({"epoch": 2, "val_acc": 0.55, "train_loss": 1.4, "train_acc": 0.6})
    writer.finish(best_val_acc=0.60, best_epoch=1, checkpoint="m.pt")

    snapshot = read_progress(target)

    assert snapshot["status"] == "done"
    assert snapshot["progress"] == 1.0
    assert snapshot["best_val_acc"] == 0.60
    assert snapshot["best_epoch"] == 1
    assert snapshot["checkpoint"] == "m.pt"
    assert len(snapshot["history"]) == 2


def test_mark_failed_keeps_previous_progress(workdir):
    target = workdir / "progress.json"

    writer = ProgressWriter(target, epochs_total=10, min_interval=0.0)
    writer.start(batches_per_epoch=5)
    writer.epoch_end({"epoch": 1, "val_acc": 0.5})

    mark_failed(target, RuntimeError("数据读坏了"))

    snapshot = read_progress(target)

    assert snapshot["status"] == "failed"
    assert "数据读坏了" in snapshot["message"]
    # 已经跑完的那一轮不能被失败覆盖掉
    assert snapshot["epoch"] == 1
    assert snapshot["epochs_total"] == 10


def test_mark_failed_without_previous_file(workdir):
    target = workdir / "never_started.json"
    mark_failed(target, "启动就崩了")

    snapshot = read_progress(target)

    assert snapshot["status"] == "failed"
    assert snapshot["epochs_total"] >= 1


def test_monitor_serves_page_and_progress(workdir):
    target = workdir / "progress.json"

    writer = ProgressWriter(target, epochs_total=4, data="x.npz", min_interval=0.0)
    writer.start(batches_per_epoch=2)
    writer.epoch_end({"epoch": 1, "val_acc": 0.61, "train_loss": 1.2, "train_acc": 0.6})

    server = make_server(target, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urllib.request.urlopen(base + "/api/progress", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["status"] == "running"
        assert payload["epoch"] == 1
        assert payload["history"][0]["val_acc"] == 0.61

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            page = response.read().decode("utf-8")

        assert response.status == 200
        assert "训练进度" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_monitor_reports_missing_progress(workdir):
    server = make_server(workdir / "nothing.json", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(base + "/api/progress", timeout=5)

        assert excinfo.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
