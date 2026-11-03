"""数据准备并行化测试：回答"数据加载是不是训练的瓶颈"。

背景：本项目**没有使用 torch.utils.data.DataLoader**，组批是
``training.dataset.collate``（numpy 补边）在主进程里做的。
所以「num_workers」这个参数不存在；本工具做的是等价实验：

* ``prefetch=0``：同步组批（当前实现）；
* ``prefetch=1/2/4``：后台线程预取后续批次，GPU 算的时候 CPU 在准备下一批。

如果预取能明显缩短每批耗时，说明数据准备确实在拖后腿；
如果几乎没变化，说明瓶颈在计算侧（Python 串行循环 / kernel launch），
加 CPU 核没有用。

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.dataloading_test
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.dataloading_test --prefetch 0,1,2,4 --seconds 5
"""

import argparse
import queue
import statistics
import threading
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from training.dataset import candidate_lengths, collate, load_dataset, make_batches
from training.model import CandidateScorer

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"


def latest_npz():
    files = sorted(DATA_DIR.glob("*.npz"), key=lambda path: path.stat().st_mtime)

    if not files:
        raise FileNotFoundError("没有 npz，先跑 export_dataset")

    return files[-1]


class Prefetch:
    """后台线程预取批次：模拟 DataLoader 的 num_workers。"""

    def __init__(self, batches, data, workers=1, maxsize=4):
        self.queue = queue.Queue(maxsize=maxsize)
        self.workers = workers
        self.threads = []
        self.batches = list(batches[: workers * 10000])
        self.data = data
        self._stop = threading.Event()

    def _produce(self, chunk):
        for batch in chunk:
            if self._stop.is_set():
                return

            self.queue.put(collate(batch, self.data))

        self.queue.put(None)

    def __enter__(self):
        size = max(1, len(self.batches) // self.workers)

        for index in range(self.workers):
            chunk = self.batches[index * size:(index + 1) * size]
            thread = threading.Thread(target=self._produce, args=(chunk,), daemon=True)
            thread.start()
            self.threads.append(thread)

        return self

    def __exit__(self, *exc):
        self._stop.set()

        return False

    def get(self):
        return self.queue.get()


def run_variant(prefetch_workers, data, batches, device, min_seconds=5.0, batch_size=64):
    """跑一种预取配置，跑满 min_seconds 秒。"""
    state_dim = int(data["states"].shape[1])
    action_dim = int(data["cand_flat"].shape[1])

    model = CandidateScorer(state_dim, action_dim).to(device)
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    steps = 0
    samples = 0
    compute_times = []
    wait_times = []
    started = time.perf_counter()

    def take_batch(index):
        return collate(batches[index % len(batches)], data)

    if prefetch_workers > 0:
        context = Prefetch(batches, data, workers=prefetch_workers)
        context.__enter__()
        get = context.get
    else:
        context = None
        get = lambda: take_batch(steps)  # noqa: E731

    try:
        while time.perf_counter() - started < min_seconds:
            wait_started = time.perf_counter()
            item = get()
            wait_times.append(time.perf_counter() - wait_started)

            if item is None:
                break

            states, cands, mask, labels, values, groups = item

            compute_started = time.perf_counter()

            states = states.to(device)
            cands = cands.to(device)
            mask = mask.to(device)
            labels = labels.to(device)
            values = values.to(device)

            scores, value = model(states, cands, mask)
            loss = F.cross_entropy(scores, labels) + 0.5 * F.binary_cross_entropy_with_logits(
                value, values
            )

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

            if device.type == "cuda":
                torch.cuda.synchronize()

            compute_times.append(time.perf_counter() - compute_started)
            steps += 1
            samples += len(labels)
    finally:
        if context is not None:
            context.__exit__(None, None, None)

    elapsed = time.perf_counter() - started

    return {
        "prefetch_workers": prefetch_workers,
        "steps": steps,
        "samples": samples,
        "seconds": round(elapsed, 2),
        "ms_per_step": round(elapsed / max(steps, 1) * 1000, 2),
        "samples_per_second": round(samples / elapsed, 1),
        "wait_ms_avg": round(statistics.mean(wait_times) * 1000, 2) if wait_times else None,
        "compute_ms_avg": round(statistics.mean(compute_times) * 1000, 2)
        if compute_times
        else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="数据准备并行化测试")
    parser.add_argument("--prefetch", default="0,1,2,4")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--data", default=None)
    parser.add_argument("--device", default="auto")

    args = parser.parse_args(argv)

    data_path = Path(args.data) if args.data else latest_npz()
    data = load_dataset(data_path)

    device = torch.device(args.device) if args.device != "auto" else torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    indices = np.arange(len(data["states"]))
    lengths = candidate_lengths(data["cand_offsets"])
    batches = make_batches(indices, lengths, batch_size=args.batch_size, shuffle=True, seed=0)

    configs = [int(part) for part in args.prefetch.split(",")]

    print("=" * 74)
    print("数据准备并行化测试（本项目没有 DataLoader，用后台线程预取作等价实验）")
    print("=" * 74)
    print(f"数据：{data_path.name}   设备：{device}   batch={args.batch_size}   每种跑 {args.seconds}s")
    print("-" * 74)
    print(f"{'预取线程':>8}{'步/秒':>9}{'ms/步':>9}{'样本/秒':>12}"
          f"{'等待数据ms':>12}{'计算ms':>9}")

    rows = []

    for workers in configs:
        row = run_variant(
            workers, data, batches, device,
            min_seconds=args.seconds, batch_size=args.batch_size,
        )
        rows.append(row)
        print(f"{row['prefetch_workers']:>8}{row['steps'] / row['seconds']:>9.2f}"
              f"{row['ms_per_step']:>9.2f}{row['samples_per_second']:>12,.0f}"
              f"{(row['wait_ms_avg'] if row['wait_ms_avg'] is not None else 0):>12.2f}"
              f"{(row['compute_ms_avg'] if row['compute_ms_avg'] is not None else 0):>9.2f}")

    baseline = next((row for row in rows if row["prefetch_workers"] == 0), None)

    if baseline:
        best = max(rows, key=lambda row: row["samples_per_second"])
        gain = best["samples_per_second"] / baseline["samples_per_second"] - 1

        print("-" * 74)
        print(f"相对同步组批：最好一档 {best['prefetch_workers']} 线程，"
              f"吞吐提升 {gain * 100:+.1f}%")

        if gain < 0.05:
            print("结论：**数据准备不是瓶颈**——加预取线程几乎没有收益。")
            print("      训练瓶颈在计算侧（Python 串行循环 / kernel launch），加 CPU 核对训练无用。")
        else:
            print("结论：预取有效，说明数据准备确实限制了训练速度。")

    print("=" * 74)
    print("说明：本项目用 numpy 组批（collate），不经过 DataLoader，故用线程预取做等价对比。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
