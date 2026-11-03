"""任意两个策略的配对对抗评估（同种子、换边各打一局）。

比 training.evaluate_neural 更通用：它只能评估"某个模型 vs 启发式/随机"，
这里可以评估**任意两个策略对象**，例如"一步前瞻 vs 行为克隆"。

配对设计（沿用项目一贯的做法）：
* 每组用同一个种子打两局，一局策略 A 坐 A 队，一局坐 B 队；
* 消除发牌差异与先手优势；
* 报告胜率、Wilson 95% 置信区间、分边胜率、成对结果。

用法：

    & .\\.venv\\Scripts\\python.exe -m tools.eval_policies --a lookahead --b heuristic --games 100
    & .\\.venv\\Scripts\\python.exe -m tools.eval_policies --a neural --b heuristic --games 100
    & .\\.venv\\Scripts\\python.exe -m tools.eval_policies --a lookahead --b neural --games 100
"""

import argparse
import json
import math
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from game_engine.game_state import GameState
from players.sampling import HeuristicSeat, RandomSeat

REPO = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO / "evaluation"


def wilson_interval(wins, total, z=1.96):
    if total == 0:
        return 0.0, 0.0

    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator

    return max(0.0, centre - margin), min(1.0, centre + margin)


def build_policy(kind, seed, args, checkpoint=None):
    if kind == "heuristic":
        return HeuristicSeat(seed, name="heuristic")

    if kind == "random":
        return RandomSeat(seed, name="random")

    if kind == "neural":
        from players.neural import NeuralPolicy

        path = checkpoint or args.checkpoint

        return NeuralPolicy(path, device=args.device, seed=seed)

    if kind == "lookahead":
        from players.lookahead import LookaheadPolicy

        return LookaheadPolicy(
            args.checkpoint,
            args.value_checkpoint,
            top_k=args.top_k,
            max_candidates=args.max_candidates,
            min_value_gap=args.min_value_gap,
            device=args.device,
            seed=seed,
            name=f"lookahead(top{args.top_k},gap{args.min_value_gap:g})",
        )

    raise ValueError(f"未知策略：{kind}")


class TeamPolicy:
    """把一个策略固定到某个队：A 队坐 0/2 号位，B 队坐 1/3 号位。"""

    def __init__(self, policy, label):
        self.policy = policy
        self.label = label
        self.name = label

    def choose(self, game, player, legal):
        return self.policy.choose(game, player, legal)


class Pairing:
    """按座位分派：A 队两个人用 policy_a，B 队两个人用 policy_b（或反之）。"""

    def __init__(self, seats):
        self.per_seat = seats

    def choose(self, game, player, legal):
        return self.per_seat[player].choose(game, player, legal)


def play_game(seats, seed, level):
    game = GameState.new_game(seed=seed, level=level)
    policies = {}

    for seat in range(4):
        factory = seats[seat]
        policies[seat] = factory(seed * 10 + seat)

    pairing = Pairing(policies)
    steps = 0

    while not game.game_over:
        steps += 1
        player = game.current_player
        legal = game.get_legal_moves(player)
        action = pairing.choose(game, player, legal)

        if action is None:
            game.pass_turn(player)
        else:
            game.play(player, action)

    first_out = game.finished_players[0]
    winner_team = "A" if first_out in (0, 2) else "B"

    return winner_team, steps


def run(a_kind, b_kind, games, seed_start, level, args):
    """每组两局：A 坐 A 队、A 坐 B 队。"""
    team_a_policy = lambda seed: build_policy(a_kind, seed, args, args.checkpoint)  # noqa: E731
    team_b_policy = lambda seed: build_policy(b_kind, seed, args, args.b_checkpoint)  # noqa: E731

    results = []
    durations = []

    for index in range(games):
        seed = seed_start + index

        for a_sits in ("A", "B"):
            if a_sits == "A":
                seats = [team_a_policy, team_b_policy, team_a_policy, team_b_policy]
            else:
                seats = [team_b_policy, team_a_policy, team_b_policy, team_a_policy]

            started = time.perf_counter()
            winner, steps = play_game(seats, seed, level)
            durations.append(time.perf_counter() - started)

            a_won = winner == a_sits
            results.append({"seed": seed, "a_sits": a_sits, "winner": winner,
                            "a_won": a_won, "steps": steps})

        if (index + 1) % 10 == 0 or index == games - 1:
            wins = sum(1 for r in results if r["a_won"])
            print(f"第 {index + 1:03d}/{games} 组 | A 胜 {wins}/{len(results)} "
                  f"| {statistics.mean(durations)*1000:.0f} ms/局")

    return results, durations


def summarize(results, durations, a_label, b_label):
    total = len(results)
    wins = sum(1 for r in results if r["a_won"])
    low, high = wilson_interval(wins, total)

    a_as_a = [r for r in results if r["a_sits"] == "A"]
    a_as_b = [r for r in results if r["a_sits"] == "B"]

    paired = []
    for index in range(0, total, 2):
        pair = results[index:index + 2]
        if len(pair) == 2:
            wins_in_pair = sum(1 for r in pair if r["a_won"])
            paired.append(wins_in_pair)

    return {
        "a": a_label,
        "b": b_label,
        "games": total,
        "a_wins": wins,
        "b_wins": total - wins,
        "a_win_rate": wins / total,
        "ci_low": low,
        "ci_high": high,
        "a_as_team_a": sum(1 for r in a_as_a if r["a_won"]) / max(len(a_as_a), 1),
        "a_as_team_b": sum(1 for r in a_as_b if r["a_won"]) / max(len(a_as_b), 1),
        "pairs_both_win": paired.count(2),
        "pairs_split": paired.count(1),
        "pairs_both_lose": paired.count(0),
        "avg_steps": statistics.mean(r["steps"] for r in results),
        "avg_ms": statistics.mean(durations) * 1000,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="任意两个策略的配对对抗评估")
    parser.add_argument("--a", default="lookahead", help="策略 A：neural / heuristic / random / lookahead")
    parser.add_argument("--b", default="heuristic", help="策略 B")
    parser.add_argument("--games", type=int, default=50, help="组数（每组两局）")
    parser.add_argument("--seed-start", type=int, default=300)
    parser.add_argument("--level", default="2")
    parser.add_argument("--checkpoint", default=None, help="策略 A 的行为克隆模型")
    parser.add_argument("--b-checkpoint", default=None, help="策略 B 的模型（用于模型对模型）")
    parser.add_argument("--value-checkpoint", default=None, help="价值网络")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=60)
    parser.add_argument("--min-value-gap", type=float, default=0.0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    if args.checkpoint is None:
        from training.self_play import latest_model

        args.checkpoint = latest_model()

    if args.value_checkpoint is None:
        values = sorted(
            (REPO / "models").glob("value_*.pt"), key=lambda p: p.stat().st_mtime
        )

        if values:
            args.value_checkpoint = values[-1]

    if args.level in ("None", "none"):
        args.level = None

    print("=" * 66)
    print("配对对抗评估")
    print("=" * 66)
    print(f"A = {args.a}    B = {args.b}    组数 = {args.games}（共 {args.games * 2} 局）")
    print(f"级牌 = {args.level}    种子 = {args.seed_start}..{args.seed_start + args.games - 1}")
    print("-" * 66)

    results, durations = run(args.a, args.b, args.games, args.seed_start, args.level, args)
    summary = summarize(results, durations, args.a, args.b)

    print("\n" + "=" * 66)
    print("评估结果")
    print("=" * 66)
    print(f"策略 A：{summary['a']}    策略 B：{summary['b']}")
    print(f"总对局：{summary['games']}")
    print(f"A 胜：{summary['a_wins']} / {summary['games']} = {summary['a_win_rate']*100:.2f}%")
    print(f"95% Wilson 置信区间：[{summary['ci_low']*100:.2f}%, {summary['ci_high']*100:.2f}%]")
    print(f"A 坐 A 队时：{summary['a_as_team_a']*100:.1f}%    "
          f"A 坐 B 队时：{summary['a_as_team_b']*100:.1f}%")
    print(f"成对结果：全胜 {summary['pairs_both_win']} 组 | "
          f"一胜一负 {summary['pairs_split']} 组 | 全负 {summary['pairs_both_lose']} 组")
    print(f"平均步数：{summary['avg_steps']:.1f}    平均耗时：{summary['avg_ms']:.0f} ms/局")

    # 前瞻策略的关键诊断：它真的执行了吗？
    if "lookahead" in (args.a, args.b):
        from players.lookahead import LookaheadPolicy

        total = LookaheadPolicy.total_decisions
        if total:
            ratio = LookaheadPolicy.total_lookaheads / total

            print(f"前瞻执行：{LookaheadPolicy.total_lookaheads}/{total} = {ratio*100:.1f}% 次决策"
                  f"（其余因候选过多退回行为克隆）")
            print(f"保守覆盖：{LookaheadPolicy.total_overrides} 次价值差不足、保留了克隆首选")
            summary["lookahead_ratio"] = ratio
            summary["lookahead_overrides"] = LookaheadPolicy.total_overrides

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = EVAL_DIR / f"policies_{args.a}_vs_{args.b}_{stamp}.csv"
    json_path = EVAL_DIR / f"policies_{args.a}_vs_{args.b}_{stamp}.json"

    csv_path.write_text(
        "seed,a_sits,winner,a_won,steps\n"
        + "\n".join(
            f"{r['seed']},{r['a_sits']},{r['winner']},{int(r['a_won'])},{r['steps']}"
            for r in results
        )
        + "\n",
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n明细：{csv_path}")
    print(f"汇总：{json_path}")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
