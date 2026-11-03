"""级牌（level）链路测试。

规则依据（2026-11-02 项目负责人确认）：

    牌力：2 < 3 < ... < A < 级牌 < 小王 < 大王

本文件验证级牌从 GameState -> legal_moves -> analyze_cards / compare_cards
以及启发式策略（players/heuristic.py）的整条链路。
"""

import random

import pytest

from game_engine.cards import create_deck
from game_engine.compare import compare_cards
from game_engine.game_state import GameState
from game_engine.legal_moves import legal_moves
from game_engine.patterns import TYPE_SINGLE, analyze_cards
from game_engine.ranks import LEVEL_VALUE, rank_value
from game_engine.wildcards import is_wildcard
from players.heuristic import (
    choose_move,
    evaluate_move,
    hand_cost,
    move_cost,
)

# 打 2 时，红桃 2 就是逢人配
WILD = ("H", "2")


def bomb(rank, count):
    return [rank] * count


def make_game(hands, level=None, first_player=0):
    """构造一个手牌可控、级牌可控的对局。"""
    game = GameState.new_game(seed=0)

    game.hands = [list(hand) for hand in hands]
    game.current_player = first_player
    game.leader = first_player
    game.level = level

    return game


def test_level_single_beats_ace_but_not_small_joker():
    """打 2 时单张 2 压 A，但压不过小王。"""
    assert compare_cards(["2"], ["A"], level="2") == 1
    assert compare_cards(["2"], ["SJ"], level="2") == -1
    assert compare_cards(["A"], ["2"], level="2") == -1


def test_without_level_two_is_still_smallest():
    """无级牌时 2 仍是最小。"""
    assert compare_cards(["2"], ["A"]) == -1
    assert compare_cards(["2"], ["3"]) == -1
    assert compare_cards(["A"], ["2"]) == 1


def test_level_bomb_beats_ace_bomb():
    """打 2 时 2222 炸弹 > AAAA 炸弹；无级牌时反过来。"""
    assert compare_cards(bomb("2", 4), bomb("A", 4), level="2") == 1
    assert compare_cards(bomb("A", 4), bomb("2", 4), level="2") == -1
    assert compare_cards(bomb("2", 4), bomb("A", 4)) == -1


def test_level_value_sits_between_ace_and_small_joker():
    assert rank_value("A") < LEVEL_VALUE < 16
    assert analyze_cards(["2"], level="2")["main_value"] == LEVEL_VALUE
    assert analyze_cards(["2"])["main_value"] == 2


@pytest.mark.parametrize("level", ["2", "5", "10", "K", "A"])
def test_level_does_not_change_other_ranks(level):
    """非级牌点数不受影响。"""
    for rank in ("3", "7", "J", "2"):
        if rank == level:
            continue

        assert rank_value(rank, level) == rank_value(rank)


def test_deck_contains_exactly_two_wildcards():
    """两副牌，逢人配最多 2 张。"""
    deck = create_deck()

    assert sum(1 for card in deck if is_wildcard(card, "2")) == 2
    assert sum(1 for card in deck if is_wildcard(card, None)) == 0


def test_new_game_keeps_level():
    game = GameState.new_game(seed=42, level="2")

    assert game.level == "2"
    assert len(game.hands) == 4


def test_game_state_passes_level_to_legal_moves():
    """打 2 时，红桃 2 是逢人配，单张按级牌算（15），能压 A。"""
    game = make_game([[WILD], ["3"], ["4"], ["5"]], level="2")

    game.last_player = 3
    game.last_play = ["A"]

    assert game.get_legal_moves(0) == [[WILD]]


def test_without_level_heart_two_cannot_beat_ace():
    """无级牌时红桃 2 只是普通 2，压不过 A。"""
    game = make_game([[WILD], ["3"], ["4"], ["5"]], level=None)

    game.last_player = 3
    game.last_play = ["A"]

    assert game.get_legal_moves(0) == []


def test_legal_moves_respects_level_for_plain_two():
    hand = ["2"]

    assert legal_moves(hand, ["A"], level="2") == [["2"]]
    assert legal_moves(hand, ["A"]) == []


def test_single_wildcard_uses_level_value():
    info = analyze_cards([WILD], level="2")

    assert info["type"] == TYPE_SINGLE
    assert info["main_rank"] == "2"
    assert info["main_value"] == LEVEL_VALUE


def test_heuristic_receives_level():
    """启发式必须用带 level 的 analyze_cards，否则万能牌组合会被判非法。"""
    assert move_cost([WILD, ("S", "3")]) == 1000.0
    assert move_cost([WILD, ("S", "3")], level="2") == 0.0
    assert evaluate_move([WILD, ("S", "3")], [WILD, ("S", "3")], level="2") < 10000


def test_hand_cost_uses_level_value():
    """级牌在剩余手牌评估里也按 15 计算（单张价值更高，成本更低）。"""
    hand = [("D", "2")]

    assert hand_cost(hand, level="2") < hand_cost(hand)
    assert hand_cost(hand, level="3") == hand_cost(hand)


def test_choose_move_infers_level_from_game_state():
    """choose_move 未显式传 level 时应从 game_state.level 读取。"""
    hand = [WILD, ("S", "3")]
    game = make_game([hand, ["4"], ["5"], ["6"]], level="2")

    selected = choose_move(
        hand,
        [[WILD, ("S", "3")]],
        rng=random.Random(0),
        game_state=game,
        player=0,
    )

    assert selected == [WILD, ("S", "3")]


def test_choose_move_accepts_explicit_level():
    hand = [WILD, ("S", "3")]

    selected = choose_move(
        hand,
        [[WILD, ("S", "3")]],
        rng=random.Random(0),
        level="2",
    )

    assert selected == [WILD, ("S", "3")]
