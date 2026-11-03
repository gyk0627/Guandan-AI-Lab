

import csv
import random
from pathlib import Path

from game_engine.game_state import GameState
from players.heuristic import choose_move


def run_match(seed, heuristic_team):
    """启发式 AI 对随机 AI。"""

    game = GameState.new_game(seed=seed)

    # 每名玩家使用独立随机数生成器
    rngs = {
        player: random.Random(seed * 100 + player)
        for player in range(4)
    }

    steps = 0
    max_steps = 1000

    while not game.game_over:
        steps += 1

        if steps > max_steps:
            raise RuntimeError(
                f"种子 {seed} 的对局超过最大行动次数"
            )

        player = game.current_player
        hand = game.hands[player]

        legal = game.get_legal_moves(player)

        player_team = "A" if player in (0, 2) else "B"
        rng = rngs[player]

        if player_team == heuristic_team:
            # 启发式 AI
            selected = choose_move(
                hand,
                legal,
                rng=rng,
                game_state=game,
                player=player
            )
        else:
            # 随机 AI
            selected = rng.choice(legal) if legal else None

        if selected is None:
            game.pass_turn(player)
        else:
            game.play(player, selected)

    first_player = game.finished_players[0]

    first_team = (
        "A" if first_player in (0, 2) else "B"
    )

    heuristic_won = first_team == heuristic_team

    return {
        "seed": seed,
        "heuristic_team": heuristic_team,
        "first_player": first_player,
        "first_team": first_team,
        "heuristic_won": heuristic_won,
        "steps": steps,
        "ranking": game.finished_players,
    }


def run_comparison(num_pairs=100, start_seed=42):

    results = []

    heuristic_wins = 0
    random_wins = 0
    total_steps = 0

    print("=" * 65)
    print("GuanDan AI Lab - 升级版启发式 AI 对照实验")
    print("=" * 65)
    print(f"实验组数：{num_pairs}")
    print(f"实际对局数：{num_pairs * 2}")
    print("-" * 65)

    for i in range(num_pairs):

        seed = start_seed + i

        # 第一场：启发式 AI 在 A 队
        result_a = run_match(seed, "A")

        # 第二场：启发式 AI 在 B 队
        result_b = run_match(seed, "B")

        results.extend([result_a, result_b])

        wins = (
            int(result_a["heuristic_won"])
            + int(result_b["heuristic_won"])
        )

        heuristic_wins += wins
        random_wins += 2 - wins

        total_steps += result_a["steps"] + result_b["steps"]

        print(
            f"第 {i + 1:03d} 组 | "
            f"启发式胜 {wins}/2 | "
            f"行动次数 "
            f"{result_a['steps']} + {result_b['steps']}"
        )

    total_games = num_pairs * 2

    heuristic_rate = heuristic_wins / total_games * 100
    random_rate = random_wins / total_games * 100
    average_steps = total_steps / total_games

    output_path = Path(__file__).with_name(
        "strategy_comparison_v2.csv"
    )

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        fieldnames = [
            "seed",
            "heuristic_team",
            "first_player",
            "first_team",
            "heuristic_won",
            "steps",
            "ranking",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for result in results:
            row = result.copy()
            row["ranking"] = str(row["ranking"])
            writer.writerow(row)

    print("\n" + "=" * 65)
    print("实验结果")
    print("=" * 65)

    print(f"总对局数：{total_games}")
    print(
        f"升级版启发式 AI：{heuristic_wins} 场 "
        f"({heuristic_rate:.1f}%)"
    )
    print(
        f"随机 AI：{random_wins} 场 "
        f"({random_rate:.1f}%)"
    )
    print(f"平均行动次数：{average_steps:.2f}")

    print("-" * 65)
    print(f"数据保存位置：{output_path.resolve()}")
    print("=" * 65)

    return results


if __name__ == "__main__":
    run_comparison(
        num_pairs=100,
        start_seed=42
    )
