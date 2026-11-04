"""一边训练、一边在网页上看实时进度（单进程，最简单的一种用法）。

网页服务和训练在同一个程序里：网页在后台线程跑，训练在主线程跑。
训练结束后网页继续开着，可以回头看曲线。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_with_monitor --epochs 40

    # 换个数据 / 改批量
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_with_monitor \\
        --data training\\data\\games_20261103_v3.npz --epochs 20 --batch-size 128

    # 不想自动开浏览器
    ... --no-open
"""

import argparse
import time
from pathlib import Path

from training.progress import DEFAULT_PATH, read_progress
from tools.train_monitor import start_in_background

REPO = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="训练 + 实时进度网页")
    parser.add_argument("--data", default=None, help="npz 路径；省略时取 training/data 下最新")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--min-candidates", type=int, default=2)
    parser.add_argument("--prefetch", type=int, default=2)
    parser.add_argument("--out", default=None, help="模型输出路径")
    parser.add_argument("--progress", default=str(DEFAULT_PATH), help="进度快照文件")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")

    args = parser.parse_args(argv)

    progress_path = Path(args.progress)

    # 上一轮的旧进度文件必须删掉，否则网页会先显示上一次训练的残留数字
    if progress_path.exists():
        progress_path.unlink()

    try:
        _, url = start_in_background(progress_path, args.port)
    except OSError as exc:
        print(f"端口 {args.port} 起不来（可能已经开着一个网页）：{exc}")
        print("换一个端口再试：--port 8767")
        return 2

    print("=" * 64)
    print("GuanDan AI Lab - 训练（带实时进度网页）")
    print("=" * 64)
    print(f"网页：{url}")
    print("训练结束后网页会继续开着，按 Ctrl+C 退出。")
    print("=" * 64)

    if not args.no_open:
        import webbrowser

        webbrowser.open(url)

    from training import train_bc

    started = time.perf_counter()

    try:
        result = train_bc.train(
            data_path=args.data,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            out_path=args.out,
            min_candidates=args.min_candidates,
            prefetch=args.prefetch,
            monitor=progress_path,
        )
    except Exception as exc:
        from training.progress import mark_failed

        mark_failed(progress_path, exc)
        print()
        print("训练失败：", exc)
        print("网页上已标红显示失败原因；按 Ctrl+C 关闭网页。")
        raise

    wall = time.perf_counter() - started
    snapshot = read_progress(progress_path) or {}

    print()
    print("=" * 64)
    print("训练完成")
    print("=" * 64)
    print(f"总耗时：{wall / 60:.1f} 分钟")
    print(f"最佳轮次：第 {result['best_epoch']} 轮，验证一致率 {result['best_val_acc']:.4f}")
    print(f"模型：{result['checkpoint']}")
    print(f"网页：{url}（还开着，按 Ctrl+C 退出）")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("已退出。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
