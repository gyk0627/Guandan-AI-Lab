"""用成对同种子 + 换座位的方式评估神经网络策略。

用法：

    .\\.venv\\Scripts\\python.exe -m training.evaluate_neural --games 100
    .\\.venv\\Scripts\\python.exe -m training.evaluate_neural --games 100 --opponent random --level 2

默认对手是启发式。注意：**数据集是用 level 轮转采的**，
所以评估时建议给一个具体级牌（例如 --level 2），否则「无级牌」是训练分布外的输入。
"""

import argparse

from players.neural import register
from evaluation.head_to_head import run_head_to_head


def main(argv=None):
    parser = argparse.ArgumentParser(description="评估神经网络策略")
    parser.add_argument("--checkpoint", default=None, help="模型路径；省略取 models 下最新")
    parser.add_argument("--games", type=int, default=100, help="组数（每组两局）")
    parser.add_argument("--seed-start", type=int, default=42)
    parser.add_argument("--opponent", default="heuristic", choices=("heuristic", "random"))
    parser.add_argument("--level", default="2", help="级牌；None 表示无级牌")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    level = None if args.level in (None, "", "none", "None") else args.level

    checkpoint = register(checkpoint=args.checkpoint, device=args.device)

    print(f"使用模型：{checkpoint}")

    result = run_head_to_head(
        games=args.games,
        seed_start=args.seed_start,
        strategy="neural",
        opponent=args.opponent,
        level=level,
        verbose=not args.json,
    )

    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
