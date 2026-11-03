"""GPU 指标共享模块：同时采集两种口径，避免被单一指标误导。

为什么需要它：
* ``nvidia-smi utilization.gpu``：统计"有 kernel 在执行的时间占比"。
  在 Windows/WDDM 上对小 kernel 频繁启动的场景会**严重低估**
  （实测同一段训练：nvidia-smi 45%，任务管理器 92~97%）。
* Windows **GPU Engine** 性能计数器：任务管理器「性能 > GPU」用的就是它，
  按引擎类型（3D / Compute / Copy / Video）统计忙闲，更能反映"显卡是不是在干活"。

本模块封装后者（``EngineSampler``），供 ``tools/train_speed.py`` 与
``tools/benchmark_suite.py`` 共用。
"""

import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE_SAMPLER = REPO / "tools" / "_gpu_engine.ps1"

ENGINE_KEYS = ("3d", "compute", "copy", "video", "other")


def _percentile(values, pct):
    if not values:
        return None

    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct / 100))

    return ordered[index]


def read_engine_csv(path):
    """解析 GPU Engine 采样 CSV，按引擎类型返回分布统计。"""
    if not path.exists():
        return {}

    columns = {key: [] for key in ENGINE_KEYS}

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split(",")

        if len(parts) < 6:
            continue

        for key, raw in zip(ENGINE_KEYS, parts[1:6]):
            try:
                columns[key].append(float(raw))
            except ValueError:
                pass

    def stats(values):
        if not values:
            return None

        return {
            "max": round(max(values), 1),
            "p95": round(_percentile(values, 95), 1),
            "mean": round(sum(values) / len(values), 1),
            "over_80_pct": round(
                sum(1 for value in values if value >= 80) / len(values) * 100, 1
            ),
        }

    return {
        "samples": len(columns["3d"]),
        "3d": stats(columns["3d"]),
        "compute": stats(columns["compute"]),
        "copy": stats(columns["copy"]),
        "video": stats(columns["video"]),
        "other": stats(columns["other"]),
    }


class EngineSampler:
    """在测量期间采集 Windows GPU Engine 计数器（任务管理器口径）。"""

    def __init__(self, out_path, interval_ms=200):
        self.out_path = Path(out_path)
        self.interval_ms = interval_ms
        self.process = None

    def __enter__(self):
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.unlink(missing_ok=True)

        self.process = subprocess.Popen(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(ENGINE_SAMPLER),
                "-Out", str(self.out_path),
                "-Seconds", "3600",
                "-IntervalMs", str(self.interval_ms),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 给 PowerShell 一点启动时间，否则会漏掉开头几个采样点
        time.sleep(1.0)

        return self

    def __exit__(self, *exc):
        if self.process:
            self.process.terminate()

            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

        self.summary = read_engine_csv(self.out_path)

        return False
