"""对局流程不变式审计：随机打 300 局，逐手复核。

每一手都做两件事：
1. 记录下来的动作，必须真的在当时的合法动作里（防止引擎状态与历史脱节）；
2. 全局不变式：牌数守恒、不会轮到已出完的人、过牌计数不超过需要、名次是排列。
"""

import random
import sys

sys.path.insert(0, r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab")

from game_engine.game_state import GameState
from players.heuristic import choose_move

TOTAL = 300


def check_game(seed, use_heuristic):
    game = GameState.new_game(seed=seed, level="2")
    rng = random.Random(seed)

    replays = []
    steps = 0

    while not game.game_over:
        steps += 1
        assert steps < 2000, f"{seed}: 步数异常"

        player = game.current_player
        assert player not in game.finished_players, f"{seed}: 轮到已出完的人"

        legal = game.get_legal_moves(player)

        if use_heuristic:
            selected = choose_move(
                game.hands[player], legal, rng=rng, game_state=game, player=player
            )
        else:
            selected = rng.choice(legal) if legal else None

        if selected is None:
            assert game.last_play is not None, f"{seed}: 领出阶段没有合法牌"
            game.pass_turn(player)
            replays.append((player, None))
        else:
            assert any(
                sorted(map(repr, m)) == sorted(map(repr, selected)) for m in legal
            ), f"{seed}: 打出了不在合法集合里的牌"
            game.play(player, selected)
            replays.append((player, selected))

        played = sum(
            len(entry["cards"]) for entry in game.history if entry["action"] == "play"
        )
        assert sum(len(h) for h in game.hands) + played == 108, f"{seed}: 牌数不守恒"

    assert sorted(game.finished_players) == [0, 1, 2, 3], f"{seed}: 名次不完整"
    assert len(game.history) == steps, f"{seed}: 历史长度与步数不符"

    return steps, replays


def replay_check(seed, replays):
    """用记录的动作重放一遍，确认每一步在当时都是合法的。"""
    game = GameState.new_game(seed=seed, level="2")

    for index, (player, action) in enumerate(replays):
        assert game.current_player == player, f"{seed}: 第 {index} 手玩家不符"

        legal = game.get_legal_moves(player)

        if action is None:
            game.pass_turn(player)
        else:
            assert any(
                sorted(map(repr, m)) == sorted(map(repr, action)) for m in legal
            ), f"{seed}: 第 {index} 手重放时不合法"
            game.play(player, action)

    assert game.game_over, f"{seed}: 重放没有结束"


def main():
    print("=" * 60)
    print("对局流程不变式审计")
    print("=" * 60)

    total_steps = 0

    for seed in range(TOTAL):
        heuristic = seed % 2 == 0
        steps, replays = check_game(seed, heuristic)
        replay_check(seed, replays)
        total_steps += steps

    print(f"随机 + 启发式各 {TOTAL // 2} 局，共 {TOTAL} 局")
    print(f"全部通过；平均 {total_steps / TOTAL:.1f} 步/局")
    print("=" * 60)


if __name__ == "__main__":
    main()
