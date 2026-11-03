
import random

from game_engine.game_state import GameState


def run_auto_game(seed=42, show_history=True):
    """运行一局四人随机策略掼蛋。"""

    game = GameState.new_game(seed=seed)

    # 使用独立随机数生成器选择出牌
    rng = random.Random(seed + 1000)

    print("=" * 60)
    print("GuanDan AI Lab - 四人自动对局")
    print("=" * 60)
    print(f"随机种子：{seed}")
    print("A队：玩家0、玩家2")
    print("B队：玩家1、玩家3")
    print("-" * 60)

    step = 0
    max_steps = 1000

    while not game.game_over:

        step += 1

        if step > max_steps:
            raise RuntimeError(
                "对局超过最大行动次数，可能存在回合逻辑问题"
            )

        player = game.current_player
        moves = game.get_legal_moves(player)

        if moves:
            # 随机选择一手合法牌
            selected = rng.choice(moves)

            game.play(player, selected)

            if show_history:
                print(
                    f"第{step:03d}步 | 玩家{player}出牌 | "
                    f"{selected} | 剩余{len(game.hands[player])}张"
                )

                if player in game.finished_players:
                    print(f"          玩家{player}已经出完！")

        else:
            # 没有可出的牌，选择过牌
            game.pass_turn(player)

            if show_history:
                print(f"第{step:03d}步 | 玩家{player}过牌")

        # 每隔一段时间显示进度
        if step % 50 == 0:
            print(f"\n已执行 {step} 步，继续对局……\n")

    print("\n" + "=" * 60)
    print("对局结束！")
    print("=" * 60)

    for position, player in enumerate(game.finished_players, start=1):
        team = "A队" if player in (0, 2) else "B队"

        print(
            f"第{position}名：玩家{player}（{team}）"
        )

    first_team = (
        "A队"
        if game.finished_players[0] in (0, 2)
        else "B队"
    )

    print("-" * 60)
    print(f"率先出完牌的队伍：{first_team}")
    print(f"总行动次数：{step}")
    print(f"历史记录数量：{len(game.history)}")
    print("=" * 60)

    return game


if __name__ == "__main__":
    run_auto_game(seed=42, show_history=False)
