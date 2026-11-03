"""GPU 利用率高频采样：核实"训练时 GPU 到底用了多少"。

背景：之前的基准用 `nvidia-smi --query-gpu=utilization.gpu`，但它夹在
``Get-Counter`` 循环里，实际采样间隔 1.5~2.5 秒，训练每轮才 19 秒，
只采到十几个点——很容易漏掉峰值。Task Manager 每秒连续采样，
能看到 92% 的平台，两者结论因此打架。

这里改成**独立线程、100ms 一次**只调 nvidia-smi，统计分布：
最大值、p95、p50、以及"高于 80% 的采样占比"。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.gpu_probe
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.gpu_probe --epochs 2 --interval 100
"""

import argparse
import statistics
import subprocess
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"


def query_gpu():
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu",
         "--format=csv,noheader,nounits"],
        text=True,
    ).strip()

    if not output:
        return None

    parts = [part.strip() for part in output.splitlines()[0].split(",")]

    return {
        "util": float(parts[0]),
        "mem": float(parts[1]),
        "power": float(parts[2]),
        "temp": float(parts[3]),
    }


class GpuProbe(threading.Thread):
    def __init__(self, interval_ms=100):
        super().__init__(daemon=True)
        self.interval = interval_ms / 1000.0
        self.samples = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                sample = query_gpu()

                if sample:
                    sample["t"] = time.perf_counter()
                    self.samples.append(sample)
            except Exception:  # noqa: BLE001 - 采样失败就跳过
                pass

            time.sleep(self.interval)

    def stop(self):
        self._stop.set()
        self.join(timeout=5)


def summarize(samples):
    utils = [sample["util"] for sample in samples]
    powers = [sample["power"] for sample in samples]
    temps = [sample["temp"] for sample in samples]
    mems = [sample["mem"] for sample in samples]

    if not utils:
        return {}

    utils_sorted = sorted(utils)

    def percentile(values, pct):
        index = min(len(values) - 1, int(len(values) * pct / 100))

        return values[index]

    return {
        "samples": len(utils),
        "util_max": max(utils),
        "util_p95": percentile(utils_sorted, 95),
        "util_p50": percentile(utils_sorted, 50),
        "util_mean": round(statistics.mean(utils), 1),
        "util_over_80_pct": round(sum(1 for value in utils if value >= 80) / len(utils) * 100, 1),
        "util_over_50_pct": round(sum(1 for value in utils if value >= 50) / len(utils) * 100, 1),
        "power_max": max(powers),
        "power_mean": round(statistics.mean(powers), 1),
        "temp_max": max(temps),
        "mem_max": max(mems),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="训练期间 GPU 利用率高频采样")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--interval", type=int, default=100, help="采样间隔（毫秒）")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--data", default=None)

    args = parser.parse_args(argv)

    data_path = Path(args.data) if args.data else sorted(
        DATA_DIR.glob("*.npz"), key=lambda path: path.stat().st_mtime
    )[-1]

    from training import train_bc
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("CUDA 不可用")

    print("=" * 70)
    print("训练期间 GPU 利用率高频采样")
    print("=" * 70)
    print(f"数据：{data_path.name}   轮数：{args.epochs}   采样间隔：{args.interval} ms")
    print("-" * 70)

    probe = GpuProbe(interval_ms=args.interval)
    probe.start()

    started = time.perf_counter()
    result = train_bc.train(
        data_path=data_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        out_path=REPO / ".test_tmp" / "gpu_probe.pt",
        verbose=False,
    )
    elapsed = time.perf_counter() - started

    probe.stop()

    (REPO / ".test_tmp" / "gpu_probe.pt").unlink(missing_ok=True)

    stats = summarize(probe.samples)

    print(f"训练 {args.epochs} 轮用时 {elapsed:.1f} 秒")
    print(f"采样点数：{stats.get('samples')}（每 {args.interval} ms 一次）")
    print("-" * 70)
    print(f"  GPU 利用率  最大 {stats['util_max']:.0f}%"
          f"   p95 {stats['util_p95']:.0f}%   p50 {stats['util_p50']:.0f}%"
          f"   均值 {stats['util_mean']:.0f}%")
    print(f"  ≥80% 的采样占比 {stats['util_over_80_pct']:.1f}%"
          f"    ≥50% 的占比 {stats['util_over_50_pct']:.1f}%")
    print(f"  功耗  最大 {stats['power_max']:.1f} W / 均值 {stats['power_mean']:.1f} W")
    print(f"  温度  最高 {stats['temp_max']:.0f} ℃   显存最大 {stats['mem_max']:.0f} MB")
    print("-" * 70)
    print("解读：p95 才代表'训练真的有在占用 GPU 的那些时刻'；")
    print("      均值会被 epoch 之间的空档拉低，不能单独用来判断 'GPU 没打满'。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
