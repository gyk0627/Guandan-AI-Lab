"""
GuanDan AI Lab - 对抗评估器（成对同种子 + 换座位）。

本模块提供三件事：

1. 策略工厂：create_policy(name_or_factory, seed)。
   目前支持 "random" / "heuristic"，
   并预留神经网络策略接入点（见文件末尾的说明）。

2. 单局执行：play_one_game(...)。
   带单局最大步数保护（默认 2000 步），
   超过就抛 GameTooLongError 报错退出，绝不静默卡死。

3. 成对评估：run_head_to_head(...)。
   同一个 seed 打两局，策略 A 分别坐 A 队（玩家 0/2）
   和 B 队（玩家 1/3）。两局牌局完全相同，
   策略 A 各拿一次首出座位（玩家 0），
   从而抵消先手与座位偏差。
   统计胜率、95% Wilson 置信区间、平均行动次数与耗时，
   并写入带时间戳的 CSV。

胜负口径与 evaluation/ 下已有脚本一致：
率先出完手牌（头游）的玩家所在队伍获胜。
"""

import argparse
import csv
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# 支持直接运行：python evaluation/head_to_head.py --games 20
if __package__ in (None, ""):
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[1]),
    )

from game_engine.game_state import GameState
from players.heuristic import choose_move


# 95% 置信度对应的标准正态分位数。
# 这里直接写常量，避免为 Wilson 区间引入 scipy。
Z_95 = 1.959963984540054

# 单局最大行动次数。正常一局大约 80~120 步，
# 2000 步已经远超合理范围，说明策略陷入死循环。
DEFAULT_MAX_STEPS = 2000

# CSV 列名（每局一行，便于后续用 pandas / Excel 分析）。
FIELDNAMES = [
    "game",
    "pair",
    "seed",
    "a_team",
    "winner_team",
    "a_won",
    "steps",
    "seconds",
    "first_player",
    "ranking",
]


class GameTooLongError(RuntimeError):
    """单局超过最大行动次数时抛出。"""


# ==================== 策略定义 ====================

class RandomPolicy:
    """随机策略：在合法出牌中等概率随机选择，没有合法牌就过牌。"""

    name = "random"

    def __init__(self, seed=0):
        self.seed = seed
        self.rng = random.Random(seed)

    def choose(self, game, player, legal_moves):
        if not legal_moves:
            return None

        return self.rng.choice(legal_moves)


class HeuristicPolicy:
    """启发式策略：复用 players.heuristic.choose_move。"""

    name = "heuristic"

    def __init__(self, seed=0):
        self.seed = seed
        self.rng = random.Random(seed)

    def choose(self, game, player, legal_moves):
        return choose_move(
            game.hands[player],
            legal_moves,
            rng=self.rng,
            game_state=game,
            player=player,
        )


# 策略注册表：名字 -> 工厂函数 factory(seed) -> 策略对象。
# 以后接神经网络策略，只要往这里注册一项即可。
STRATEGY_FACTORIES = {
    "random": lambda seed: RandomPolicy(seed),
    "heuristic": lambda seed: HeuristicPolicy(seed),
}


def _strategy_label(strategy):
    """给策略取一个人类可读的名字，用于表格和 CSV。"""

    if isinstance(strategy, str):
        return strategy

    if hasattr(strategy, "choose"):
        return getattr(strategy, "name", type(strategy).__name__)

    return getattr(strategy, "__name__", "custom")


def create_policy(strategy, seed=0):
    """
    按名称或工厂创建策略对象。

    参数：
        strategy：以下三种写法都支持
            1. 注册名，如 "random" / "heuristic"
            2. 工厂函数 factory(seed) -> 策略对象
            3. 已经构造好的策略对象（带 choose 方法）
        seed：传给工厂的随机种子

    要求策略对象实现：
        choose(game, player, legal_moves) -> 牌列表 或 None
    """

    if isinstance(strategy, str):
        if strategy not in STRATEGY_FACTORIES:
            supported = "、".join(sorted(STRATEGY_FACTORIES))
            raise ValueError(
                f"未知策略：{strategy}，目前支持：{supported}"
            )

        factory = STRATEGY_FACTORIES[strategy]

    elif hasattr(strategy, "choose"):
        # 直接传入策略对象，不需要工厂
        return strategy

    elif callable(strategy):
        factory = strategy

    else:
        raise TypeError(
            "策略必须是注册名、工厂函数或带 choose 方法的对象"
        )

    policy = factory(seed)

    if not hasattr(policy, "choose"):
        raise TypeError(
            "策略工厂必须返回带 choose(game, player, legal_moves) 方法的对象"
        )

    return policy


# ==================== 统计工具 ====================

def wilson_interval(successes, total, z=Z_95):
    """
    计算二项比例的 Wilson 置信区间（不依赖 scipy）。

    Wilson 区间比常见的正态近似更稳，
    在 0/10、10/10 这类极端比例下也不会越界。

    参数：
        successes：成功次数（例如策略 A 的胜场）
        total：总次数（例如总对局数）
        z：正态分位数，95% 置信度对应 1.96

    返回：
        (下界, 上界)，已裁剪到 [0, 1]
        总次数为 0 时返回 (0.0, 1.0)，表示完全不确定
    """

    if total < 0:
        raise ValueError("总次数不能为负数")

    if successes < 0 or successes > total:
        raise ValueError("成功次数必须在 0 到总次数之间")

    if total == 0:
        return 0.0, 1.0

    p = successes / total

    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            p * (1.0 - p) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    return lower, upper


def summarize_records(records):
    """
    根据逐局记录统计胜率、Wilson 区间与行动次数。

    这是一个纯函数，便于用假数据单独做单元测试，
    不必真的跑几十上百局。
    """

    total = len(records)

    if total == 0:
        raise ValueError("没有对局记录，无法统计")

    wins = sum(1 for record in records if record["a_won"])
    losses = total - wins

    win_rate = wins / total
    lower, upper = wilson_interval(wins, total)

    by_team = {}

    for team in ("A", "B"):
        subset = [
            record
            for record in records
            if record["a_team"] == team
        ]
        team_wins = sum(1 for record in subset if record["a_won"])

        by_team[team] = {
            "games": len(subset),
            "wins": team_wins,
            "win_rate": (
                team_wins / len(subset) if subset else 0.0
            ),
        }

    # 成对结果：同一 seed 的两局都赢 / 一胜一负 / 都输
    pair_results = {}

    for record in records:
        pair_results.setdefault(record["pair"], []).append(
            bool(record["a_won"])
        )

    sweep_win = sum(
        1 for results in pair_results.values() if all(results)
    )
    sweep_loss = sum(
        1 for results in pair_results.values()
        if not any(results)
    )
    split = len(pair_results) - sweep_win - sweep_loss

    total_steps = sum(record["steps"] for record in records)
    total_seconds = sum(record["seconds"] for record in records)

    return {
        "total_games": total,
        "strategy_wins": wins,
        "opponent_wins": losses,
        "win_rate": win_rate,
        "wilson_low": lower,
        "wilson_high": upper,
        "avg_steps": total_steps / total,
        "total_steps": total_steps,
        "total_seconds": total_seconds,
        "seconds_per_game": total_seconds / total,
        "by_team": by_team,
        "pair_outcomes": {
            "total": len(pair_results),
            "sweep_win": sweep_win,
            "split": split,
            "sweep_loss": sweep_loss,
        },
    }


# ==================== 单局执行 ====================

def play_one_game(
    seed,
    strategy_a,
    strategy_b,
    a_team="A",
    first_player=0,
    level=None,
    max_steps=DEFAULT_MAX_STEPS,
):
    """
    运行一局，返回逐局记录。

    策略 A 占据 a_team 对应的两个座位，
    策略 B 占据另外两个座位。
    每个座位使用独立的随机数生成器，
    种子由 (seed, player) 派生，保证整局可复现。
    """

    if a_team not in ("A", "B"):
        raise ValueError("a_team 只能是 'A' 或 'B'")

    if first_player not in (0, 1, 2, 3):
        raise ValueError("first_player 只能是 0~3")

    start = time.perf_counter()

    game = GameState.new_game(
        seed=seed,
        first_player=first_player,
        level=level,
    )

    policies = {}

    for player in range(4):
        team = "A" if player in (0, 2) else "B"
        spec = strategy_a if team == a_team else strategy_b
        policies[player] = create_policy(spec, seed * 100 + player)

    steps = 0

    while not game.game_over:
        steps += 1

        if steps > max_steps:
            raise GameTooLongError(
                f"种子 {seed} 的对局超过 {max_steps} 步仍未结束，"
                f"策略 A 坐 {a_team} 队，已中止以避免卡死"
            )

        player = game.current_player
        legal_moves = game.get_legal_moves(player)

        selected = policies[player].choose(
            game,
            player,
            legal_moves,
        )

        if selected is None:
            # 领出阶段必须出牌，这里出现 None 说明策略返回了非法动作
            if game.last_play is None:
                raise RuntimeError(
                    f"种子 {seed} 第 {steps} 步：玩家 {player} "
                    f"在领出阶段没有出牌，手牌 "
                    f"{len(game.hands[player])} 张"
                )

            game.pass_turn(player)

        else:
            game.play(player, selected)

    seconds = time.perf_counter() - start

    first_out = game.finished_players[0]
    winner_team = "A" if first_out in (0, 2) else "B"

    return {
        "seed": seed,
        "a_team": a_team,
        "winner_team": winner_team,
        "a_won": winner_team == a_team,
        "steps": steps,
        "seconds": seconds,
        "first_player": first_player,
        "ranking": "-".join(
            str(player) for player in game.finished_players
        ),
    }


# ==================== 成对评估 ====================

def _next_output_path(output_dir, prefix="head_to_head"):
    """生成带时间戳的输出路径，同一分钟内重名时自动加序号。"""

    if output_dir is None:
        directory = Path(__file__).resolve().parent
    else:
        directory = Path(output_dir)

    directory.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = directory / f"{prefix}_{stamp}.csv"

    index = 2

    while path.exists():
        path = directory / f"{prefix}_{stamp}_{index}.csv"
        index += 1

    return path


def run_head_to_head(
    games=100,
    seed_start=42,
    strategy="heuristic",
    opponent="random",
    first_player=0,
    level=None,
    max_steps=DEFAULT_MAX_STEPS,
    output_dir=None,
    verbose=True,
    print_table=True,
):
    """
    成对同种子 + 换座位评估。

    参数：
        games：组数，每组两局，默认 100 组 = 200 局
        seed_start：起始随机种子
        strategy：策略 A（被评估的一方）
        opponent：对手策略
        first_player：每局首位出牌玩家
        level：级牌，None 表示无级牌模式
        max_steps：单局最大行动次数，超过抛 GameTooLongError
        output_dir：CSV 输出目录，默认 evaluation/
        verbose：是否打印逐局进度
        print_table：是否打印汇总表格

    返回：
        包含配置、统计结果与 CSV 路径的字典
    """

    if games < 1:
        raise ValueError("组数至少为 1")

    if max_steps < 1:
        raise ValueError("单局最大行动次数至少为 1")

    strategy_name = _strategy_label(strategy)
    opponent_name = _strategy_label(opponent)

    if verbose:
        print("=" * 62)
        print("GuanDan AI Lab - 成对同种子对战评估（换座位）")
        print("=" * 62)
        print(f"策略 A：{strategy_name}    策略 B：{opponent_name}")
        print(
            f"组数：{games} 组（共 {games * 2} 局）    "
            f"起始种子：{seed_start}    "
            f"单局步数上限：{max_steps}"
        )
        print("-" * 62)

    records = []

    for pair in range(games):
        seed = seed_start + pair

        # 同一 seed 打两局：策略 A 先坐 A 队，再坐 B 队
        for a_team in ("A", "B"):
            record = play_one_game(
                seed=seed,
                strategy_a=strategy,
                strategy_b=opponent,
                a_team=a_team,
                first_player=first_player,
                level=level,
                max_steps=max_steps,
            )

            record["pair"] = pair + 1
            record["game"] = len(records) + 1
            records.append(record)

            if verbose:
                print(
                    f"第 {pair + 1:03d} 组 | 策略A 坐 {a_team} 队 | "
                    f"种子 {seed} | 胜者 {record['winner_team']} 队 | "
                    f"策略A {'胜' if record['a_won'] else '负'} | "
                    f"行动 {record['steps']} | "
                    f"{record['seconds'] * 1000:.0f} ms"
                )

    stats = summarize_records(records)

    csv_path = _next_output_path(output_dir)

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:

        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()

        for record in records:
            writer.writerow({
                key: record[key]
                for key in FIELDNAMES
            })

    config = {
        "strategy": strategy_name,
        "opponent": opponent_name,
        "pairs": games,
        "total_games": len(records),
        "seed_start": seed_start,
        "first_player": first_player,
        "level": level,
        "max_steps": max_steps,
    }

    summary = dict(config)
    summary.update(stats)
    summary["csv_path"] = str(csv_path)

    if print_table:
        _print_summary(summary)

    return summary


def _print_summary(summary):
    """打印人类可读的汇总表格。"""

    total = summary["total_games"]
    wins = summary["strategy_wins"]
    losses = summary["opponent_wins"]
    win_rate = summary["win_rate"] * 100
    lower = summary["wilson_low"] * 100
    upper = summary["wilson_high"] * 100

    print("\n" + "=" * 62)
    print("评估结果")
    print("=" * 62)

    print(f"策略 A：{summary['strategy']}")
    print(f"策略 B：{summary['opponent']}")
    print(f"总对局数：{total}（{summary['pairs']} 组 × 2 局）")
    print("-" * 62)

    print(
        f"策略 A 胜场：{wins} / {total}    "
        f"胜率：{win_rate:.2f}%"
    )
    print(
        f"95% Wilson 置信区间：[{lower:.2f}%, {upper:.2f}%]"
    )
    print(
        f"策略 B 胜场：{losses} / {total}    "
        f"胜率：{losses / total * 100:.2f}%"
    )

    by_team = summary["by_team"]

    for team in ("A", "B"):
        data = by_team[team]
        rate = data["win_rate"] * 100
        print(
            f"策略 A 坐 {team} 队时："
            f"{data['wins']} / {data['games']} 胜"
            f"（{rate:.1f}%）"
        )

    pairs = summary["pair_outcomes"]

    print(
        f"成对结果：全胜 {pairs['sweep_win']} 组 | "
        f"一胜一负 {pairs['split']} 组 | "
        f"全负 {pairs['sweep_loss']} 组"
    )
    print(f"平均行动次数：{summary['avg_steps']:.2f}")
    print(
        f"总耗时：{summary['total_seconds']:.2f} s"
        f"（平均 {summary['seconds_per_game'] * 1000:.1f} ms/局）"
    )

    print("-" * 62)
    print(f"逐局明细已保存：{summary['csv_path']}")
    print("=" * 62)


# ==================== 命令行入口 ====================

def build_parser():
    """构造命令行解析器，供脚本入口和 main.py 复用。"""

    parser = argparse.ArgumentParser(
        prog="head_to_head.py",
        description="GuanDan AI Lab - 成对同种子 + 换座位的对战评估器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python evaluation/head_to_head.py --games 100\n"
            "  python evaluation/head_to_head.py --games 50 "
            "--opponent heuristic\n"
            "  python main.py evaluate --games 20 --json\n"
        ),
    )

    parser.add_argument(
        "--games",
        type=int,
        default=100,
        help="比赛组数，每组两局（默认 100 组 = 200 局）",
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
        choices=sorted(STRATEGY_FACTORIES),
        help="被评估的策略 A（默认 heuristic）",
    )
    parser.add_argument(
        "--opponent",
        default="random",
        choices=sorted(STRATEGY_FACTORIES),
        help="对手策略（默认 random）",
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
    parser.add_argument(
        "--output-dir",
        default=None,
        help="CSV 输出目录（默认 evaluation/）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出统计摘要（不打印表格，仍然写 CSV）",
    )

    return parser


def main(argv=None):
    """命令行入口，返回退出码。"""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.games < 1:
        parser.error("--games 至少为 1")

    try:
        summary = run_head_to_head(
            games=args.games,
            seed_start=args.seed_start,
            strategy=args.strategy,
            opponent=args.opponent,
            first_player=args.first_player,
            level=args.level,
            max_steps=args.max_steps,
            output_dir=args.output_dir,
            verbose=not args.json,
            print_table=not args.json,
        )

    except GameTooLongError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())


# ================= 神经网络策略接入点（预留） =================
#
# 以后接神经网络策略时，不需要改动本文件的评估逻辑，
# 只要实现与 RandomPolicy / HeuristicPolicy 相同的接口：
#
#     class NeuralPolicy:
#         name = "neural"
#
#         def __init__(self, seed=0, model_path=None):
#             self.rng = random.Random(seed)
#             self.model = 加载模型(model_path)
#
#         def choose(self, game, player, legal_moves):
#             # 可以复用 training/state_encoder.py 的
#             # encode_state(game, player) 与 encode_action(move)，
#             # 把所有候选动作编码成向量后前向计算，
#             # 返回分数最高的一手牌，或返回 None 表示过牌。
#             ...
#
# 然后注册工厂（其余代码一行都不用改）：
#
#     STRATEGY_FACTORIES["neural"] = lambda seed: NeuralPolicy(seed)
#
# create_policy / play_one_game / run_head_to_head 都接受：
#   - 注册名（"random" / "heuristic" / "neural"）
#   - 工厂函数 factory(seed) -> 策略对象
#   - 已构造好的策略对象（只要带 choose 方法）
#
# 注意：神经网络策略若使用全局随机数或 dropout，
# 必须用传入的 seed 初始化，否则成对评估失去可复现性。
