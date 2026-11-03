"""训练记速器：**真跑** N 轮训练（默认 20），逐轮计时后汇报速度。

不是"跑几步外推"，而是把训练完整跑完，用每一轮的实测耗时算速度。

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_speed
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_speed --task value
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_speed --epochs 10 --batch-size 64
"""

import argparse
import shutil
import statistics
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"
TMP_DIR = REPO / ".test_tmp" / "train_speed"


def human_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f} 秒"

    if seconds < 3600:
        return f"{seconds / 60:.1f} 分钟"

    return f"{seconds / 3600:.1f} 小时"


def display_width(text):
    """终端显示宽度：中文/全角算 2 格，其余算 1 格。

    直接用 ``str.ljust`` 按字符数补空格，遇到中文就会错位——
    因为"任务"是 2 个字符但占 4 个格子。
    """
    width = 0

    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1

    return width


def pad(text, width, align="left"):
    """按**显示宽度**补空格，保证中英混排也能对齐。"""
    text = str(text)
    gap = max(0, width - display_width(text))

    if align == "right":
        return " " * gap + text

    return text + " " * gap


def table_row(cells, widths, aligns):
    return "".join(
        pad(cell, width, align)
        for cell, width, align in zip(cells, widths, aligns)
    )


def latest_npz():
    files = sorted(DATA_DIR.glob("*.npz"), key=lambda path: path.stat().st_mtime)

    if not files:
        raise FileNotFoundError(f"{DATA_DIR} 下没有 npz，先跑 export_dataset")

    return files[-1]


def per_epoch_seconds(history):
    """把累计耗时换算成每轮耗时。"""
    cumulative = [float(record.get("seconds", 0.0)) for record in history]
    result = []

    for index, value in enumerate(cumulative):
        previous = cumulative[index - 1] if index else 0.0
        result.append(max(value - previous, 0.0))

    return result


def system_memory():
    """用 ctypes 读系统内存（不依赖 psutil）。"""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None

        total_gb = status.ullTotalPhys / 1e9
        used_gb = (status.ullTotalPhys - status.ullAvailPhys) / 1e9

        return {"total_gb": round(total_gb, 1), "used_gb": round(used_gb, 1),
                "percent": round(status.dwMemoryLoad, 0)}
    except Exception:  # noqa: BLE001 - 读不到就不显示
        return None


def report(title, history, total_samples, epochs, extra=None):
    times = per_epoch_seconds(history)
    total = sum(times)

    print("-" * 66)
    print(f"实测结果（{title}，真跑 {len(times)} 轮）")
    print("-" * 66)

    widths = (8, 12, 12, 12, 14)
    aligns = ("left", "right", "right", "right", "right")
    print(table_row(("轮次", "本轮耗时", "数据准备", "GPU计算", "显存峰值"), widths, aligns))

    cumulative = 0.0

    for index, (record, seconds) in enumerate(zip(history, times), start=1):
        cumulative += seconds
        prep = record.get("prep_seconds")
        compute = record.get("compute_seconds")
        vram = record.get("peak_vram_gb")

        print(
            table_row(
                (
                    f"第 {index:02d} 轮",
                    f"{seconds:.1f} 秒",
                    f"{prep:.1f} 秒" if prep is not None else "-",
                    f"{compute:.1f} 秒" if compute is not None else "-",
                    f"{vram:.2f} GB" if vram else "-",
                ),
                widths,
                aligns,
            )
        )

    print("-" * 66)
    print(f"  总耗时      {human_time(total)}（{total:.1f} 秒）")
    print(f"  平均每轮    {human_time(total / len(times))}"
          f"（最快 {min(times):.1f}s / 中位 {statistics.median(times):.1f}s / 最慢 {max(times):.1f}s）")

    processed = total_samples * len(times)
    print(f"  样本吞吐    {processed:,} 条 / {total:.1f} 秒 = "
          f"{processed / total:,.0f} 条/秒")

    preps = [record.get("prep_seconds") for record in history if record.get("prep_seconds") is not None]
    computes = [record.get("compute_seconds") for record in history if record.get("compute_seconds") is not None]
    vrams = [record.get("peak_vram_gb") for record in history if record.get("peak_vram_gb")]

    if preps and computes:
        prep_total = sum(preps)
        compute_total = sum(computes)
        share = prep_total / (prep_total + compute_total) * 100 if (prep_total + compute_total) else 0
        print(f"  时间构成    数据准备 {prep_total:.1f}s（{share:.0f}%）"
              f" / 计算 {compute_total:.1f}s（{100 - share:.0f}%）")

    if vrams:
        print(f"  显存峰值    PyTorch 分配 {max(vrams):.2f} GB"
              f"（不含 CUDA 上下文约 0.3~0.5 GB）")

    memory = system_memory()

    if memory:
        print(f"  系统内存    已用 {memory['used_gb']} / {memory['total_gb']} GB"
              f"（{memory['percent']:.0f}%）")

    if extra:
        for line in extra:
            print(f"  {line}")

    print("=" * 66)

    return {
        "epochs": len(times),
        "total_seconds": round(total, 1),
        "avg_epoch_seconds": round(total / len(times), 1),
        "samples_per_second": round(processed / total, 1),
    }


def run_bc(epochs, batch_size, data_path, seed=0, device="auto"):
    from training import train_bc
    from tools.gpu_metrics import EngineSampler

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TMP_DIR / "train_speed_bc.pt"

    # 训练期间同时采 GPU Engine（任务管理器口径）：nvidia-smi 在 Windows 上会低估
    with EngineSampler(TMP_DIR / "engine_bc.csv") as engine_sampler:
        started = time.perf_counter()
        result = train_bc.train(
            data_path=data_path,
            epochs=epochs,
            batch_size=batch_size,
            seed=seed,
            device=device,
            out_path=out_path,
            min_candidates=2,
            verbose=True,
        )
        wall = time.perf_counter() - started

    history = result["history"]
    history[-1]["seconds"] = wall  # 用墙钟总时长校正（含验证集与收尾）

    extra = [
        f"最佳验证一致率   {result['best_val_acc']:.4f}（第 {result['best_epoch']} 轮）",
    ]

    stats = report("行为克隆 / 候选打分网络", history,
                   int(result.get("train_samples", 0)) or _train_samples(data_path),
                   epochs, extra)

    engine = getattr(engine_sampler, "summary", {}).get("3d")

    if engine:
        print(f"  GPU 占用(3D) 峰值 {engine['max']:.0f}% / p95 {engine['p95']:.0f}%"
              f" / 均值 {engine['mean']:.0f}%（≥80% 的采样占 {engine['over_80_pct']:.0f}%）")
        print("             ↑ 任务管理器口径；nvidia-smi 在 Windows 上会低估，两者不要混用")

    out_path.unlink(missing_ok=True)

    return stats


def run_value(epochs, batch_size, data_path, seed=0, device="auto"):
    from training import train_value

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TMP_DIR / "train_speed_value.pt"

    started = time.perf_counter()
    result = train_value.train(
        data_path=data_path,
        epochs=epochs,
        batch_size=batch_size,
        seed=seed,
        device=device,
        out_path=out_path,
        verbose=True,
    )
    wall = time.perf_counter() - started

    history = result["history"]
    history[-1]["seconds"] = wall

    extra = [
        f"最佳验证 AUC     {result['best_val_auc']:.4f}（第 {result['best_epoch']} 轮）",
    ]

    stats = report("价值网络", history, _value_samples(data_path), epochs, extra)

    out_path.unlink(missing_ok=True)

    return stats


def _train_samples(data_path):
    from training.dataset import load_dataset, split_by_game

    data = load_dataset(data_path)
    train_index, _ = split_by_game(data["game_index"], val_fraction=0.1, seed=0)

    return len(train_index)


def _value_samples(data_path):
    from training.dataset import load_dataset, split_by_game

    data = load_dataset(data_path)
    train_index, _ = split_by_game(data["game_index"], val_fraction=0.1, seed=0)

    return len(train_index)


def main(argv=None):
    parser = argparse.ArgumentParser(description="训练记速器（真跑 N 轮）")
    parser.add_argument("--task", choices=("bc", "value", "both"), default="bc")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--data", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto")

    args = parser.parse_args(argv)

    data_path = Path(args.data) if args.data else latest_npz()

    print("=" * 66)
    print("训练记速器：真跑训练，逐轮计时")
    print("=" * 66)
    print(f"数据：{data_path.name}")
    print(f"轮数：{args.epochs}   任务：{args.task}")
    print("=" * 66)

    try:
        if args.task in ("bc", "both"):
            run_bc(
                args.epochs,
                args.batch_size or 64,
                data_path,
                seed=args.seed,
                device=args.device,
            )

        if args.task in ("value", "both"):
            run_value(
                args.epochs,
                args.batch_size or 256,
                data_path,
                seed=args.seed,
                device=args.device,
            )
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
