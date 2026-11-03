"""
GuanDan AI Lab - 固定种子性能基准。

用途：防止以后改引擎或策略时悄悄变慢。
固定种子跑 N 局，输出每局毫秒数、平均步数，
并对每局耗时做 min / median / max 统计。
"""

import argparse
import sys
from pathlib import Path

# 支持直接运行：python evaluation/benchmark.py --games 20
if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1]),
    )

from evaluation.head_to_head import (
    DEFAULT_MAX_STEPS,
    GameTooLongError,
    play_one_game,
)


DEFAULT_GAMES = 20


def summarize_durations(durations):
    """
    对每局耗时（秒）做简单统计。

    这是一个纯函数，不依赖对局，
    方便用假数据单独做单元测试。
    """

    values = sorted(float(value) for value in durations)

    if not values:
        return {
            "count": 0,
            "total": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
        }

    count = len(values)
    middle = count // 2

    if count % 2 == 1:
        median = values[middle]
    else:
        median = (values[middle - 1] + values[middle]) / 2.0

    return {
        "count": count,
        "total": sum(values),
        "mean": sum(values) / count,
        "min": values[0],
        "median": median,
        "max": values[-1],
    }


def run_benchmark(
    num_games=DEFAULT_GAMES,
    seed_start=42,
    strategy="heuristic",
    first_player=0,
    level=None,
    max_steps=DEFAULT_MAX_STEPS,
    verbose=True,
):
    """
    固定种子跑 N 局自对弈，统计耗时与步数。

    返回：
        包含逐局明细、平均步数与耗时统计的字典
    """

    if num_games < 1:
        raise ValueError("基准局数至少为 1")

    if verbose:
        print("=" * 62)
        print("GuanDan AI Lab - 性能基准测试")
        print("=" * 62)
        print(
            f"策略：{strategy}    "
            f"局数：{num_games}    "
            f"起始种子：{seed_start}"
        )
        print("-" * 62)

    rows = []

    for index in range(num_games):
        seed = seed_start + index

        record = play_one_game(
            seed=seed,
            strategy_a=strategy,
            strategy_b=strategy,
            a_team="A",
            first_player=first_player,
            level=level,
            max_steps=max_steps,
        )

        rows.append({
            "game": index + 1,
            "seed": seed,
            "steps": record["steps"],
            "seconds": record["seconds"],
        })

        if verbose:
            print(
                f"第 {index + 1:03d} 局 | 种子 {seed} | "
                f"行动 {record['steps']} | "
                f"{record['seconds'] * 1000:.1f} ms"
            )

    durations = summarize_durations(
        row["seconds"] for row in rows
    )

    total_steps = sum(row["steps"] for row in rows)
    avg_steps = total_steps / num_games

    if verbose:
        print("\n" + "=" * 62)
        print("基准结果")
        print("=" * 62)
        print(f"固定种子局数：{num_games}")
        print(f"平均步数：{avg_steps:.2f}（总步数 {total_steps}）")
        print(
            f"每局耗时：平均 {durations['mean'] * 1000:.1f} ms | "
            f"最小 {durations['min'] * 1000:.1f} ms | "
            f"中位数 {durations['median'] * 1000:.1f} ms | "
            f"最大 {durations['max'] * 1000:.1f} ms"
        )
        print(f"总耗时：{durations['total']:.2f} s")
        print("=" * 62)

    return {
        "config": {
            "strategy": strategy,
            "games": num_games,
            "seed_start": seed_start,
            "first_player": first_player,
            "level": level,
            "max_steps": max_steps,
        },
        "games": rows,
        "avg_steps": avg_steps,
        "total_steps": total_steps,
        "durations": durations,
    }


def build_parser():
    """构造命令行解析器。"""

    parser = argparse.ArgumentParser(
        prog="benchmark.py",
        description=(
            "GuanDan AI Lab - 固定种子性能基准"
            "（防止改慢没人发现）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python evaluation/benchmark.py --games 20\n"
            "  python main.py bench --games 10 --seed-start 100\n"
        ),
    )

    parser.add_argument(
        "--games",
        type=int,
        default=DEFAULT_GAMES,
        help=f"基准局数（默认 {DEFAULT_GAMES}）",
    )
    parser.add_argument(
        "--seed-start",
        type=int,
        default=42,
        help="起始随机种子（默认 42）",
    )
    parser.add_argument(
        "--strategy",
        default="heuristic",
        choices=["heuristic", "random"],
        help="自对弈使用的策略（默认 heuristic）",
    )
    parser.add_argument(
        "--first-player",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="每局首位出牌玩家（默认 0）",
    )
    parser.add_argument(
        "--level",
        default=None,
        help="级牌（2~A），默认 None 表示无级牌模式",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        help=f"单局最大行动次数，超过即报错（默认 {DEFAULT_MAX_STEPS}）",
    )

    return parser


def main(argv=None):
    """命令行入口，返回退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.games < 1:
        parser.error("--games 至少为 1")

    try:
        run_benchmark(
            num_games=args.games,
            seed_start=args.seed_start,
            strategy=args.strategy,
            first_player=args.first_player,
            level=args.level,
            max_steps=args.max_steps,
        )

    except GameTooLongError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
