"""对局引擎测试：回合、过牌、牌权、名次、不变式。"""

import random
from collections import Counter

import pytest

from game_engine.cards import create_deck
from game_engine.game_state import GameState
from players.heuristic import choose_move


def make_game(hands, first_player=0, level=None):
    """构造一个手牌可控的对局（初始校验只在 __init__ 里做）。"""
    game = GameState.new_game(seed=0)

    game.hands = [list(hand) for hand in hands]
    game.current_player = first_player
    game.leader = first_player
    game.level = level

    return game


def test_new_game_deals_108_cards():
    game = GameState.new_game(seed=42)

    assert len(game.hands) == 4
    assert all(len(hand) == 27 for hand in game.hands)

    total = Counter()
    for hand in game.hands:
        total.update(hand)

    assert total == Counter(create_deck())


def test_deal_is_reproducible():
    a = GameState.new_game(seed=7)
    b = GameState.new_game(seed=7)
    c = GameState.new_game(seed=8)

    assert a.hands == b.hands
    assert a.hands != c.hands


def test_teammate():
    assert GameState.teammate(0) == 2
    assert GameState.teammate(1) == 3
    assert GameState.teammate(2) == 0
    assert GameState.teammate(3) == 1


def test_can_beat_partner():
    """2026-11-03 负责人确认：**可以压队友的牌**（此前实现是硬禁止）。"""
    game = make_game([[], ["5"], [], []], first_player=1)

    game.last_player = 3          # 1 的队友
    game.last_play = ["4"]

    assert game.get_legal_moves(1) == [["5"]]

    game.play(1, ["5"])

    assert game.last_play == ["5"]
    assert game.last_player == 1


def test_can_answer_opponent():
    game = make_game([[], ["5"], [], []], first_player=1)

    game.last_player = 0
    game.last_play = ["4"]

    assert game.get_legal_moves(1) == [["5"]]


def test_cannot_pass_when_leading():
    game = GameState.new_game(seed=1)

    with pytest.raises(ValueError):
        game.pass_turn(game.current_player)


def test_trick_resets_after_everyone_passes():
    game = make_game(
        [["3", "9"], ["4"], ["5"], ["6"]],
        first_player=0,
    )

    game.play(0, ["3"])
    assert game.last_play == ["3"]
    assert game.current_player == 1
    assert 0 not in game.finished_players

    game.pass_turn(1)
    game.pass_turn(2)
    game.pass_turn(3)

    # 四个人都走完一圈，牌权回到最后出牌的人
    assert game.last_play is None
    assert game.last_player is None
    assert game.pass_count == 0
    assert game.current_player == 0


def test_play_removes_cards_and_tracks_history():
    game = make_game([["3", "4"], ["5"], ["6"], ["7"]], first_player=0)

    game.play(0, ["3"])

    assert game.hands[0] == ["4"]
    assert game.history[-1] == {"player": 0, "action": "play", "cards": ["3"]}


def test_playing_cards_not_in_hand_raises():
    game = make_game([["3"], ["4"], ["5"], ["6"]], first_player=0)

    with pytest.raises(ValueError):
        game.play(0, ["9"])


def test_playing_wrong_turn_raises():
    game = make_game([["3"], ["4"], ["5"], ["6"]], first_player=0)

    with pytest.raises(ValueError):
        game.play(1, ["4"])


def test_playing_illegal_pattern_raises():
    game = make_game([["3", "3", "3", "5"], ["6"], ["7"], ["8"]], first_player=0)

    with pytest.raises(ValueError):
        game.play(0, ["3", "3", "3", "5"])


def test_finished_player_is_skipped():
    game = make_game([["3"], ["4"], ["5"], ["6"]], first_player=0)

    game.play(0, ["3"])

    assert 0 in game.finished_players
    assert game.current_player == 1


def test_game_ends_with_full_ranking():
    """一直打到底，名次必须是完整的四名。"""
    game = GameState.new_game(seed=42)
    rng = random.Random(0)
    steps = 0

    while not game.game_over:
        steps += 1
        assert steps < 1000

        player = game.current_player
        assert player not in game.finished_players

        moves = game.get_legal_moves(player)

        if moves:
            game.play(player, rng.choice(moves))
        else:
            game.pass_turn(player)

    assert len(game.finished_players) == 4
    assert sorted(game.finished_players) == [0, 1, 2, 3]


@pytest.mark.parametrize("seed", range(20))
def test_card_conservation(seed):
    """任何时刻：四家剩余手牌 + 已打出的牌 = 108。"""
    game = GameState.new_game(seed=seed)
    rng = random.Random(seed)

    while not game.game_over:
        player = game.current_player
        moves = game.get_legal_moves(player)

        if moves:
            game.play(player, rng.choice(moves))
        else:
            game.pass_turn(player)

        played = sum(
            len(entry["cards"])
            for entry in game.history
            if entry["action"] == "play"
        )
        assert sum(len(hand) for hand in game.hands) + played == 108


@pytest.mark.parametrize("seed", range(10))
def test_heuristic_games_complete(seed):
    """启发式 AI 自对弈必须能走完。"""
    game = GameState.new_game(seed=seed)
    rng = random.Random(seed + 1000)

    while not game.game_over:
        player = game.current_player
        moves = game.get_legal_moves(player)
        selected = choose_move(
            game.hands[player], moves, rng=rng, game_state=game, player=player
        )

        if selected is None:
            game.pass_turn(player)
        else:
            game.play(player, selected)

    assert len(game.finished_players) == 4


def test_level_is_passed_to_legal_moves():
    """打 2 时，手里只剩 2 也能压 A。"""
    game = make_game([["2"], ["3"], ["4"], ["5"]], first_player=0, level="2")

    game.last_player = 3
    game.last_play = ["A"]

    assert game.get_legal_moves(0) == [["2"]]
