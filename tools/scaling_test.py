"""CPU 扩展性测试：进程数 1/2/4/8/12/16 下，自我对弈的吞吐如何变化。

目的：**先测清楚再买硬件**——避免花钱买一堆核、吞吐却没涨。

每一档记录：
* 每秒完整对局数、每秒决策数；
* 相对单进程的加速比与并行效率；
* 整机 CPU 占用率、可用内存、GPU 利用率与显存峰值（外挂 PowerShell 采样器）。

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.scaling_test
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.scaling_test --games 24
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.scaling_test --configs 1,2,4,8
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from training.self_play import run_parallel_self_play

REPO = Path(__file__).resolve().parent.parent
TMP = REPO / ".test_tmp" / "scaling"
SAMPLER = REPO / "tools" / "_sampler.ps1"
OUT_DIR = REPO / "evaluation"


def start_sampler(csv_path):
    process = subprocess.Popen(
        [
            sys.executable, "-X", "utf8", "-m", "tools.resource_sampler",
            "--out", str(csv_path), "--seconds", "900", "--interval-ms", "200",
        ],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return process


def stop_sampler(process):
    process.terminate()

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def read_samples(csv_path):
    """读采样 CSV，返回各项的平均值/峰值。"""
    if not csv_path.exists():
        return {}

    cpu = []
    free = []
    gpu = []
    gpu_mem = []

    for line in csv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.strip().split(",")

        if len(parts) < 5:
            continue

        try:
            cpu.append(float(parts[1]))
            free.append(float(parts[2]))
        except ValueError:
            continue

        if parts[3]:
            try:
                gpu.append(float(parts[3]))
            except ValueError:
                pass

        if parts[4]:
            try:
                gpu_mem.append(float(parts[4]))
            except ValueError:
                pass

    def avg(values):
        return round(sum(values) / len(values), 1) if values else None

    return {
        "cpu_avg": avg(cpu),
        "cpu_peak": round(max(cpu), 1) if cpu else None,
        "free_mem_avg": avg(free),
        "gpu_avg": avg(gpu),
        "gpu_peak": round(max(gpu), 1) if gpu else None,
        "gpu_mem_peak": round(max(gpu_mem), 0) if gpu_mem else None,
        "samples": len(cpu),
    }


def run_config(workers, games, seed_start, threads=0, seats=("neural", "neural", "neural", "neural")):
    TMP.mkdir(parents=True, exist_ok=True)
    out_path = TMP / f"scaling_w{workers}.jsonl"
    csv_path = TMP / f"scaling_w{workers}.csv"

    # 每个工作进程的 CPU 线程数。默认 torch 会在每个进程里开满线程，
    # 16 个进程 × 8 线程 = 128 线程挤在 18 核上，实测吞吐会崩。
    if threads > 0:
        import os

        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[name] = str(threads)

    sampler = start_sampler(csv_path)
    started = time.perf_counter()

    try:
        _, manifest = run_parallel_self_play(
            games=games,
            workers=workers,
            seats=seats,
            seed_start=seed_start,
            temperature=1.0,
            epsilon=0.05,
            out_path=out_path,
            verbose=False,
        )
        elapsed = time.perf_counter() - started
        error = None
    except Exception as exception:  # noqa: BLE001 - 一档失败不应中断整个测试
        elapsed = time.perf_counter() - started
        manifest = None
        error = f"{type(exception).__name__}: {exception}"
    finally:
        stop_sampler(sampler)

    resources = read_samples(csv_path)

    if out_path.exists():
        out_path.unlink()

    if manifest is None:
        return {"workers": workers, "error": error, "elapsed": round(elapsed, 2)}

    return {
        "workers": workers,
        "games": manifest["games"],
        "decisions": manifest["decisions"],
        "elapsed": round(elapsed, 2),
        "games_per_second": round(manifest["games"] / elapsed, 2),
        "decisions_per_second": round(manifest["decisions"] / elapsed, 1),
        **resources,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="CPU 扩展性测试")
    parser.add_argument("--configs", default="1,2,4,8,12,16")
    parser.add_argument("--games", type=int, default=24)
    parser.add_argument("--seed-start", type=int, default=960000)
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="每个进程限制多少个 CPU 线程（0=不限制，用 torch 默认）",
    )
    parser.add_argument(
        "--seats",
        default="neural,neural,neural,neural",
        help="四家策略；用 heuristic,heuristic,heuristic,heuristic 可测纯 CPU 扩展性",
    )

    args = parser.parse_args(argv)

    configs = [int(part) for part in args.configs.split(",")]
    games = args.games
    seats = tuple(part.strip() for part in args.seats.split(","))

    if len(seats) != 4:
        raise SystemExit("--seats 必须给 4 个")

    print("=" * 78)
    print("CPU 扩展性测试（自我对弈）")
    print("=" * 78)
    print(f"每档对局数：{games}   进程档位：{configs}   每进程线程："
          f"{args.threads if args.threads else '不限制'}")
    print(f"座位策略：{','.join(seats)}")
    print("-" * 78)

    rows = []

    for workers in configs:
        print(f"  进程 {workers:>2d} 运行中…", end="", flush=True)
        row = run_config(workers, games, args.seed_start, threads=args.threads, seats=seats)
        row["threads_per_proc"] = args.threads
        row["seats"] = list(seats)
        rows.append(row)

        if row.get("error"):
            print(f"\r  进程 {workers:>2d} 失败：{row['error']}")
        else:
            print(f"\r  进程 {workers:>2d} | {row['elapsed']:6.1f}s | "
                  f"{row['games_per_second']:5.2f} 局/秒 | "
                  f"{row['decisions_per_second']:7.1f} 决策/秒")

    baseline = next((row for row in rows if row["workers"] == 1 and not row.get("error")), None)
    base_rate = baseline["games_per_second"] if baseline else None

    print("-" * 78)
    print("汇总")
    print("-" * 78)

    header = (f"{'进程':>4}{'局/秒':>9}{'加速比':>8}{'效率':>8}"
              f"{'CPU%':>8}{'可用内存MB':>12}{'GPU%':>7}{'显存MB':>9}{'耗时s':>8}")
    print(header)
    print("-" * 78)

    for row in rows:
        if row.get("error"):
            print(f"{row['workers']:>4}  失败：{row['error']}")
            continue

        speedup = (row["games_per_second"] / base_rate) if base_rate else None
        efficiency = (speedup / row["workers"] * 100) if speedup else None

        speedup_text = f"{speedup:.2f}x" if speedup else "-"
        efficiency_text = f"{efficiency:.0f}%" if efficiency else "-"
        cpu_text = f"{row['cpu_avg']:.0f}" if row.get("cpu_avg") else "-"
        mem_text = f"{row['free_mem_avg']:.0f}" if row.get("free_mem_avg") else "-"
        gpu_text = f"{row['gpu_avg']:.0f}" if row.get("gpu_avg") else "-"
        vram_text = f"{row['gpu_mem_peak']:.0f}" if row.get("gpu_mem_peak") else "-"

        print(
            f"{row['workers']:>4}"
            f"{row['games_per_second']:>9.2f}"
            f"{speedup_text:>8}"
            f"{efficiency_text:>8}"
            f"{cpu_text:>8}"
            f"{mem_text:>12}"
            f"{gpu_text:>7}"
            f"{vram_text:>9}"
            f"{row['elapsed']:>8.1f}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / "scaling_test.json"
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 78)
    print(f"结果：{out_json}")
    print("说明：加速比 = 该档局/秒 ÷ 单进程局/秒；效率 = 加速比 ÷ 进程数。")
    print("      GPU 为四家神经网络推理共用，进程越多越容易在 GPU 上排队。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
