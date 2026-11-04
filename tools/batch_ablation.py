"""E20 batch 大小消融：吞吐 vs 精度。

背景（E19）：固定宽度合成张量下，batch 64→512 步时几乎不变
（2.12→2.03ms），说明每步开销被 kernel launch 主导。
本实验在**真实数据集**上验证同一结论，并看短程精度是否受损。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.batch_ablation
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.batch_ablation --batch-sizes 64,128,256,512 --epochs 3
"""

import argparse
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"
OUT = REPO / "evaluation" / "batch_ablation.json"
# 消融只关心吞吐与短程精度，产出的 checkpoint 没有保留价值。
# 必须写到临时目录：train_bc 在 out_path=None 时会写到 models/bc_<数据名>.pt，
# 那会覆盖真正训练好的模型（2026-11-04 就这么覆盖过 bc_games_20261103_v3.pt 一次）。
SCRATCH = REPO / ".test_tmp" / "ablation"


def latest_npz():
    files = sorted(DATA_DIR.glob("games_*.npz"), key=lambda path: path.stat().st_mtime)

    if not files:
        raise FileNotFoundError("没有 games_*.npz，先跑 export_dataset")

    return files[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="batch 大小消融")
    parser.add_argument("--batch-sizes", default="64,128,256,512")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--data", default=None)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument(
        "--lr-scale",
        default="fixed",
        choices=("fixed", "linear"),
        help="fixed：所有 batch 同一 lr；linear：lr ∝ batch（大 batch 常用做法）",
    )
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--prefetch",
        type=int,
        default=0,
        help="后台组批线程数（0 = 关）；用于 A/B 对照 collate 是否成为瓶颈",
    )

    args = parser.parse_args(argv)

    from training import train_bc

    data_path = Path(args.data) if args.data else latest_npz()
    sizes = [int(part) for part in args.batch_sizes.split(",")]

    print("=" * 78)
    print("E20 batch 大小消融：吞吐 vs 精度（真实数据集）")
    print("=" * 78)
    print(f"数据：{data_path.name}   轮数：{args.epochs}   lr：{args.lr}")
    print("-" * 78)
    print(f"{'batch':>7}{'总耗时s':>10}{'轮均s':>9}{'样本/秒':>12}"
          f"{'最佳验证一致率':>14}{'末轮训练loss':>13}")

    rows = []

    SCRATCH.mkdir(parents=True, exist_ok=True)

    for batch_size in sizes:
        # 大 batch 通常按比例放大 lr；linear 模式下 lr = base_lr * batch/64
        lr = args.lr * batch_size / 64 if args.lr_scale == "linear" else args.lr
        scratch = SCRATCH / f"ablation_b{batch_size}.pt"

        started = time.perf_counter()
        result = train_bc.train(
            data_path=data_path,
            epochs=args.epochs,
            batch_size=batch_size,
            lr=lr,
            seed=0,
            out_path=scratch,
            min_candidates=2,
            verbose=False,
            prefetch=args.prefetch,
        )
        wall = time.perf_counter() - started

        # 用完即删（连同自动生成的侧车 .json）
        for path in (scratch, scratch.with_suffix(".json")):
            if path.exists():
                path.unlink()

        history = result["history"]
        epochs_run = len(history)
        epoch_seconds = wall / max(epochs_run, 1)
        train_samples = int(result.get("train_samples") or 0)
        samples_per_second = (
            train_samples * epochs_run / wall if wall > 0 and train_samples else 0
        )

        row = {
            "batch_size": batch_size,
            "lr": lr,
            "wall_seconds": round(wall, 1),
            "epoch_seconds": round(epoch_seconds, 1),
            "train_samples": train_samples,
            "samples_per_second": round(samples_per_second, 0),
            "best_val_acc": round(float(result["best_val_acc"]), 4),
            "final_train_loss": history[-1]["train_loss"],
            "final_val_acc": history[-1]["val_acc"],
            "history": history,
        }
        rows.append(row)

        print(f"{batch_size:>7}{wall:>10.1f}{epoch_seconds:>9.1f}"
              f"{samples_per_second:>12,.0f}{row['best_val_acc']:>14.4f}"
              f"{history[-1]['train_loss']:>13.4f}")

    print("-" * 78)

    baseline = rows[0]

    if baseline["samples_per_second"] > 0:
        for row in rows[1:]:
            speedup = row["samples_per_second"] / baseline["samples_per_second"]
            delta_acc = row["best_val_acc"] - baseline["best_val_acc"]
            print(f"batch {row['batch_size']:>4}：吞吐 {speedup:.2f}× "
                  f"（相对 batch {baseline['batch_size']}），"
                  f"最佳验证一致率 {delta_acc:+.4f}")
    else:
        for row in rows[1:]:
            print(f"batch {row['batch_size']:>4}：耗时 {row['wall_seconds']:.1f}s"
                  f"（相对 {baseline['wall_seconds']:.1f}s），"
                  f"最佳验证一致率 {row['best_val_acc'] - baseline['best_val_acc']:+.4f}")

    best = max(rows, key=lambda item: item["samples_per_second"])
    print(f"\n吞吐最高：batch {best['batch_size']}"
          f"（{best['samples_per_second']:,.0f} 样本/秒，"
          f"{best['samples_per_second'] / baseline['samples_per_second']:.2f}× 于 batch {baseline['batch_size']}）")
    print("注意：轮数只有 "
          f"{args.epochs}，精度对比只是‘短程参考’，长程收敛需单独验证；")
    print("      大 batch 通常需要按比例调大 lr，本实验固定 lr 以隔离吞吐变量。")

    payload = {
        "data": data_path.name,
        "epochs": args.epochs,
        "lr": args.lr,
        "prefetch": args.prefetch,
        "rows": rows,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果：{out_path}")

    print("=" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
