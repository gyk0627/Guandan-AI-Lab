"""训练进度快照：训练进程往文件里写，网页/监控程序读。

设计约束（为什么这么简单）：
1. **不依赖第三方库**，只用标准库；训练进程和网页是两个程序，用文件通信最稳。
2. **原子写**：先写 `.tmp` 再 `os.replace`，网页永远读不到写了一半的 JSON。
3. **写不崩训练**：进度写失败只记一条警告，绝不让训练因为磁盘/权限问题中断。
4. 写频率有节流（默认 0.5 秒一次），不会因为每个 batch 都写文件而拖慢训练。

用法（训练侧）：见 `training/train_bc.py` 的 `monitor=` 参数。
用法（网页侧）：`python -m tools.train_monitor`。
"""

import json
import os
import time
from pathlib import Path

# 默认进度文件位置；放仓库内，网页和训练都在同一台机器上
DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".test_tmp" / "train_progress.json"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class ProgressWriter:
    """把训练进度原子地写到 `path`。

    典型调用顺序：
        writer = ProgressWriter(path, epochs_total=40, data="x.npz")
        writer.start(batches_per_epoch=4870, ...)
        writer.batch(epoch=1, batch=10)          # 每个 batch（内部节流）
        writer.epoch_end(record)                 # 每轮结束，带完整指标
        writer.finish(best_val_acc=..., best_epoch=...)
    """

    def __init__(self, path=None, epochs_total=1, data=None, device=None,
                 batch_size=None, lr=None, min_interval=0.5):
        self.path = Path(path) if path else DEFAULT_PATH
        self.epochs_total = max(int(epochs_total), 1)
        self.min_interval = float(min_interval)

        self._payload = {
            "status": "starting",       # starting / running / done / failed
            "message": None,
            "data": data,
            "device": device,
            "batch_size": batch_size,
            "lr": lr,
            "epochs_total": self.epochs_total,
            "epoch": 0,
            "batches_per_epoch": 0,
            "batch": 0,
            "progress": 0.0,            # 0.0 ~ 1.0，含轮内小格
            "train_loss": None,
            "train_acc": None,
            "val_acc": None,
            "best_val_acc": None,
            "best_epoch": None,
            "epoch_seconds": None,
            "elapsed_seconds": 0.0,
            "eta_seconds": None,
            "samples_per_second": None,
            "history": [],
            "started_at": _now(),
            "updated_at": _now(),
        }
        self._last_write = 0.0
        self._started = time.perf_counter()
        self._dirty = True

    # ---------- 对外接口 ----------

    def start(self, batches_per_epoch=0, train_samples=None, val_samples=None):
        self._payload["status"] = "running"
        self._payload["batches_per_epoch"] = int(batches_per_epoch)
        self._payload["train_samples"] = train_samples
        self._payload["val_samples"] = val_samples
        self._write(force=True)

    def batch(self, epoch, batch, loss=None, samples_done=None):
        """训练途中更新（内部节流，默认 0.5 秒最多写一次）。"""
        payload = self._payload
        payload["epoch"] = int(epoch)
        payload["batch"] = int(batch)

        if loss is not None:
            payload["train_loss"] = round(float(loss), 4)

        if samples_done is not None:
            payload["samples_done"] = int(samples_done)

        done_epochs = int(epoch) - 1
        per_epoch = max(int(payload.get("batches_per_epoch") or 0), 1)
        in_epoch = min(int(batch) / per_epoch, 1.0)
        payload["progress"] = round((done_epochs + in_epoch) / self.epochs_total, 4)

        self._update_timing()
        self._write()

    def epoch_end(self, record):
        """一轮结束：写入这一轮的完整指标，并更新 ETA。"""
        payload = self._payload
        payload["epoch"] = int(record.get("epoch", payload["epoch"]))
        payload["batch"] = payload.get("batches_per_epoch") or 0
        payload["train_loss"] = record.get("train_loss")
        payload["train_acc"] = record.get("train_acc")
        payload["val_loss"] = record.get("val_loss")
        payload["val_acc"] = record.get("val_acc")
        payload["val_group_acc"] = record.get("val_group_acc")
        payload["epoch_seconds"] = record.get("seconds")
        payload["peak_vram_gb"] = record.get("peak_vram_gb")
        payload["history"] = list(payload.get("history") or []) + [record]

        best = payload.get("best_val_acc")
        if record.get("val_acc") is not None:
            if best is None or record["val_acc"] > best:
                payload["best_val_acc"] = record["val_acc"]
                payload["best_epoch"] = record["epoch"]

        payload["progress"] = round(payload["epoch"] / self.epochs_total, 4)
        self._update_timing()
        self._write(force=True)

    def finish(self, **fields):
        self._payload["status"] = "done"
        self._payload["progress"] = 1.0
        self._update_timing()
        self._payload.update(fields)
        self._write(force=True)

    def fail(self, message):
        self._payload["status"] = "failed"
        self._payload["message"] = str(message)[-800:]
        self._update_timing()
        self._write(force=True)

    # ---------- 内部 ----------

    def _update_timing(self):
        elapsed = time.perf_counter() - self._started
        payload = self._payload
        payload["elapsed_seconds"] = round(elapsed, 1)

        progress = float(payload.get("progress") or 0.0)

        # 第一轮还没跑完时没有"每轮耗时"可参考，就直接按整体进度外推，
        # 这样刚开训几秒就能给出预计剩余时间，而不是空着。
        if 0.02 < progress < 1.0:
            payload["eta_seconds"] = round(elapsed * (1.0 - progress) / progress, 0)

        samples_done = payload.get("samples_done")

        if samples_done and elapsed > 1.0:
            payload["samples_per_second"] = round(samples_done / elapsed, 0)
        elif payload.get("epoch_seconds") and payload.get("train_samples"):
            per_epoch = float(payload["epoch_seconds"])
            payload["samples_per_second"] = round(payload["train_samples"] / per_epoch, 0)

    def _write(self, force=False):
        now = time.perf_counter()

        if not force and (now - self._last_write) < self.min_interval:
            self._dirty = True
            return

        self._last_write = now
        self._dirty = False
        self._payload["updated_at"] = _now()

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(
                json.dumps(self._payload, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError:
            # 进度写不进去不该毁掉训练：宁可不显示，也要继续算
            pass


def read_progress(path=None):
    """读进度快照；文件不存在或正在被替换时返回 None。"""
    target = Path(path) if path else DEFAULT_PATH

    try:
        # utf-8-sig：顺手容忍记事本另存时加的 BOM，否则手改过的进度文件会读不出来
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def mark_failed(path, message):
    """训练异常退出时把快照标成 failed（否则网页会一直显示"正在训练"）。"""
    target = Path(path)
    payload = read_progress(target) or {"epochs_total": 1, "epoch": 0, "progress": 0.0}
    payload["status"] = "failed"
    payload["message"] = str(message)[-800:]
    payload["updated_at"] = _now()

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass

    return payload
