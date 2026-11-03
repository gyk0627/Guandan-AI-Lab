
import random

from replay.game_logger import GameLogger
from game_engine.game_state import GameState
from players.heuristic import choose_move


def run_auto_game(seed=42, show_history=True):

    game = GameState.new_game(seed=seed)

    # 初始化日志记录器
    logger = GameLogger(seed=seed)

    rng = random.Random(seed + 1000)

    print("=" * 60)
    print("GuanDan AI Lab - 升级版启发式 AI 对局")
    print("=" * 60)

    step = 0
    max_steps = 1000

    while not game.game_over:

        step += 1

        if step > max_steps:
            raise RuntimeError("超过最大行动次数")

        player = game.current_player
        hand = game.hands[player]

        # 获取当前合法动作
        moves = game.get_legal_moves(player)

        # 保存行动前的状态
        hand_before = list(hand)

        previous_play = (
            list(game.last_play)
            if game.last_play is not None
            else None
        )

        previous_player = game.last_player
        legal_count = len(moves)

        # AI 决策
        selected = choose_move(
            hand,
            moves,
            rng=rng,
            game_state=game,
            player=player
        )

        # 执行行动
        if selected is not None:

            game.play(player, selected)
            action_type = "play"

            if show_history:
                print(
                    f"第{step:03d}步 | 玩家{player}出牌 | "
                    f"{selected} | "
                    f"剩余{len(game.hands[player])}张"
                )

                if player in game.finished_players:
                    print(f"玩家{player}已经出完！")

        else:

            game.pass_turn(player)
            action_type = "pass"

            if show_history:
                print(f"第{step:03d}步 | 玩家{player}过牌")

        # 记录本次行动
        logger.record_turn(
            game=game,
            player=player,
            action=selected,
            action_type=action_type,
            hand_before=hand_before,
            previous_play=previous_play,
            previous_player=previous_player,
            legal_count=legal_count
        )

    # 对局结束
    print("\n" + "=" * 60)
    print("对局结束！")
    print("=" * 60)

    for position, player in enumerate(
        game.finished_players,
        start=1
    ):
        team = "A队" if player in (0, 2) else "B队"
        print(f"第{position}名：玩家{player}（{team}）")

    first_player = game.finished_players[0]

    first_team = (
        "A队" if first_player in (0, 2) else "B队"
    )

    print("-" * 60)
    print(f"率先出完牌的队伍：{first_team}")
    print(f"总行动次数：{step}")
    print("=" * 60)

    # 保存对局结束记录
    logger.finish(game)

    return game.finished_players, step


if __name__ == "__main__":
    run_auto_game(seed=42)
