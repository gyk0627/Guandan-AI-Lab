"""速度测试：跑一小批对局并导出，打印「每秒几局 / 每秒几条」。

用途：换服务器前先在本机测一遍，据此估算租多少核、1000 万局要跑多久。
纯命令行，不渲染任何界面。

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.speed_test
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.speed_test --games 100
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.speed_test --games 30 --seats heuristic
"""

import argparse
import contextlib
import io
import shutil
import time
from pathlib import Path

from training.export_dataset import export
from training.self_play import run_self_play

REPO = Path(__file__).resolve().parent.parent


def human_hours(hours):
    if hours is None:
        return "?"

    if hours < 1:
        return f"{hours * 60:.1f} 分钟"

    return f"{hours:.1f} 小时"


def main(argv=None):
    print("[已合并] 这个脚本现在归到统一入口：python -m tools.benchmark run --preset standard")
    print("          （旧命令仍可用；新报告格式见 tools/benchmark.py 顶部说明）")
    print()
    parser = argparse.ArgumentParser(description="生成对局与导出的速度测试")
    parser.add_argument("--games", type=int, default=60, help="测多少局（默认 60）")
    parser.add_argument(
        "--seats",
        default="neural,neural,neural,neural",
        help="四家策略；heuristic 更快、neural 更接近真实训练",
    )
    parser.add_argument("--seed-start", type=int, default=880000)

    args = parser.parse_args(argv)

    seats = tuple(part.strip() for part in args.seats.split(","))

    if len(seats) != 4:
        raise SystemExit("--seats 必须给 4 个，用逗号分隔")

    # 注意：系统 TEMP 在受限环境下不可写，统一放到仓库内的临时目录
    workdir = REPO / ".test_tmp" / f"speed_{int(time.time())}"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        print("=" * 62)
        print("生成对局与导出的速度测试")
        print("=" * 62)
        print(f"对局数：{args.games}   座位策略：{','.join(seats)}")
        print("-" * 62)

        # ---- 阶段 1：生成对局 ----
        out_path = workdir / "speed.jsonl"
        started = time.perf_counter()
        last_report = [0.0]

        def on_game(done, total, decisions):
            now = time.perf_counter()
            elapsed = now - started

            if done == total or now - last_report[0] >= 1.0:
                last_report[0] = now
                rate = done / elapsed if elapsed else 0.0
                dps = decisions / elapsed if elapsed else 0.0
                print(
                    f"  生成 {done:>4d}/{total} 局 | {elapsed:6.1f}s | "
                    f"{rate:5.2f} 局/秒 | {dps:7.1f} 决策/秒"
                )

        _, manifest = run_self_play(
            games=args.games,
            seats=seats,
            seed_start=args.seed_start,
            temperature=1.0,
            epsilon=0.05,
            out_path=out_path,
            verbose=False,
            progress=on_game,
        )

        gen_seconds = time.perf_counter() - started
        decisions = int(manifest["decisions"])
        games_per_second = args.games / gen_seconds
        decisions_per_second = decisions / gen_seconds

        print("-" * 62)
        print(f"  生成合计：{args.games} 局 / {decisions} 条决策 / {gen_seconds:.1f}s")
        print(f"           {games_per_second:.2f} 局/秒   {decisions_per_second:.0f} 决策/秒")

        # ---- 阶段 2：导出 ----
        print("-" * 62)
        export_started = time.perf_counter()
        last_export = [0.0]
        export_lines = []

        def on_export(done, total, samples):
            now = time.perf_counter()

            if done == total or now - last_export[0] >= 1.0:
                last_export[0] = now
                elapsed = now - export_started
                rate = samples / elapsed if elapsed else 0.0
                export_lines.append(
                    f"  导出 {done:>4d}/{total} 局 | {elapsed:6.1f}s | {rate:7.0f} 样本/秒"
                )

        # 导出器自己会打印一堆统计，这里屏蔽掉，只保留我们的进度行
        with contextlib.redirect_stdout(io.StringIO()):
            _, meta = export(
                out_path, out_path=workdir / "speed.npz", progress=on_export
            )

        for line in export_lines:
            print(line)

        export_seconds = time.perf_counter() - export_started
        samples = int(meta["samples"])
        samples_per_second = samples / export_seconds
        export_decisions_per_second = decisions / export_seconds

        print("-" * 62)
        print(f"  导出合计：{samples} 条样本 / {export_seconds:.1f}s")
        print(f"           {samples_per_second:.0f} 样本/秒   "
              f"{export_decisions_per_second:.0f} 决策/秒")

        # ---- 换算 ----
        print("=" * 62)
        print("规模换算（按本次实测速度）")
        print("=" * 62)
        print(f"  {'生成对局':<16}{'预计耗时':>16}")

        for target in (1_000, 10_000, 100_000, 10_000_000):
            hours = target / games_per_second / 3600
            print(f"  {target:>10,} 局{'':<6}{human_hours(hours):>16}")

        print(f"  {'导出样本':<16}{'预计耗时':>16}")

        for target in (100_000, 1_000_000, 10_000_000):
            hours = target / samples_per_second / 3600
            print(f"  {target:>10,} 条{'':<6}{human_hours(hours):>16}")

        print("=" * 62)
        print("说明：单进程；多进程约按核数加速（实测 4 进程 3.0 倍）。")
        print("      数字随显卡状态、级牌、温度采样波动，多跑几次取稳定值。")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
