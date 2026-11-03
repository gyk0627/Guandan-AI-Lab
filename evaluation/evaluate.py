
import csv
import random
from collections import Counter
from pathlib import Path

from game_engine.game_state import GameState


def run_one_game(seed):
    """运行一局随机策略对局。"""

    game = GameState.new_game(seed=seed)
    rng = random.Random(seed + 1000)

    steps = 0
    max_steps = 1000

    while not game.game_over:
        steps += 1

        if steps > max_steps:
            raise RuntimeError(
                f"第 {seed} 局超过最大行动次数"
            )

        player = game.current_player
        moves = game.get_legal_moves(player)

        if moves:
            selected = rng.choice(moves)
            game.play(player, selected)
        else:
            game.pass_turn(player)

    return game.finished_players, steps


def run_evaluation(num_games=100, start_seed=42):
    """批量运行比赛、统计并保存 CSV。"""

    team_first_out = Counter()
    player_ranks = Counter()
    total_steps = 0

    records = []

    print("=" * 60)
    print("GuanDan AI Lab - 批量对局评估")
    print("=" * 60)
    print(f"比赛局数：{num_games}")
    print(f"起始随机种子：{start_seed}")
    print("-" * 60)

    for i in range(num_games):
        seed = start_seed + i

        ranking, steps = run_one_game(seed)

        first_player = ranking[0]
        first_team = (
            "A队" if first_player in (0, 2) else "B队"
        )

        team_first_out[first_team] += 1
        total_steps += steps

        for position, player in enumerate(ranking, start=1):
            player_ranks[player] += position

        records.append({
            "game": i + 1,
            "seed": seed,
            "first_player": first_player,
            "first_team": first_team,
            "player0_rank": ranking.index(0) + 1,
            "player1_rank": ranking.index(1) + 1,
            "player2_rank": ranking.index(2) + 1,
            "player3_rank": ranking.index(3) + 1,
            "steps": steps,
        })

        print(
            f"第 {i + 1:03d} 局 | "
            f"率先出完：玩家{first_player}（{first_team}） | "
            f"行动次数：{steps}"
        )

    # 保存 CSV
    output_path = Path(__file__).with_name("results.csv")

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        fieldnames = [
            "game",
            "seed",
            "first_player",
            "first_team",
            "player0_rank",
            "player1_rank",
            "player2_rank",
            "player3_rank",
            "steps",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(records)

    # 输出统计
    print("\n" + "=" * 60)
    print("批量评估结果")
    print("=" * 60)

    print("\n率先出完牌的队伍：")

    for team in ("A队", "B队"):
        count = team_first_out[team]
        rate = count / num_games * 100

        print(f"{team}：{count} 局 | {rate:.1f}%")

    print("\n玩家平均名次：")

    for player in range(4):
        average = player_ranks[player] / num_games
        team = "A队" if player in (0, 2) else "B队"

        print(
            f"玩家{player}（{team}）："
            f"{average:.2f} 名"
        )

    average_steps = total_steps / num_games

    print("\n其他统计：")
    print(f"总行动次数：{total_steps}")
    print(f"平均每局行动次数：{average_steps:.2f}")

    print("-" * 60)
    print(f"实验数据已保存：{output_path.resolve()}")
    print("=" * 60)

    print(
        "\n注意：当前统计的是率先出完牌的队伍，"
        "还不是完整升级规则下的正式比赛胜率。"
    )


if __name__ == "__main__":
    run_evaluation(
        num_games=100,
        start_seed=42
    )
