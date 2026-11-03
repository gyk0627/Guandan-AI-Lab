"""合法动作生成测试。"""

from collections import Counter

import pytest

from game_engine.legal_moves import generate_candidates, legal_moves
from game_engine.patterns import (
    TYPE_BOMB,
    TYPE_FLUSH_STRAIGHT,
    TYPE_PAIR_CHAIN,
    TYPE_STRAIGHT,
    analyze_cards,
)
from game_engine.ranks import rank_of


def signature(cards):
    return tuple(sorted(repr(card) for card in cards))


def test_all_generated_moves_are_valid():
    hand = [
        "2", "3", "3", "3", "4", "4", "5", "5", "5", "5",
        "6", "7", "8", "9", "10", "J", "Q", "K", "A",
        "SJ", "BJ", ("S", "6"), ("S", "7"), ("S", "8"),
        ("S", "9"), ("S", "10"), ("H", "K"),
    ]

    for move in generate_candidates(hand):
        assert analyze_cards(move) is not None, f"生成了非法牌型：{move}"


def test_generated_moves_are_unique():
    hand = ["3", "3", "4", "4", "5", "5", "6", "7", "8"]

    signatures = [signature(move) for move in generate_candidates(hand)]

    assert len(signatures) == len(set(signatures))


def test_pair_chain_is_generated():
    hand = ["3", "3", "4", "4", "5", "5", "9"]

    types = {analyze_cards(move)["type"] for move in generate_candidates(hand)}

    assert TYPE_PAIR_CHAIN in types

    chain = [
        move for move in generate_candidates(hand)
        if analyze_cards(move)["type"] == TYPE_PAIR_CHAIN
    ]

    # 连对（木板）恰好 3 对，所以只会是 6 张
    assert chain
    assert all(len(move) == 6 for move in chain)


def test_pair_chain_requires_exactly_three_pairs():
    """2 对和 4 对都不合法，只有 3 对会出现在候选里。"""
    hand = ["3", "3", "4", "4", "5", "5", "6", "6"]

    chain = [
        move for move in generate_candidates(hand)
        if analyze_cards(move)["type"] == TYPE_PAIR_CHAIN
    ]

    assert chain
    assert {len(move) for move in chain} == {6}
    # 3-4-5 和 4-5-6 两种窗口都应该生成
    assert len(chain) >= 2


def test_all_nine_straights_are_generated():
    hand = [
        ("S", "2"), ("H", "3"), ("S", "4"), ("H", "5"), ("S", "6"),
        ("H", "7"), ("S", "8"), ("H", "9"), ("S", "10"), ("H", "J"),
        ("S", "Q"), ("H", "K"), ("S", "A"),
    ]

    straights = [
        move for move in generate_candidates(hand)
        if analyze_cards(move)["type"] == TYPE_STRAIGHT
    ]

    assert len(straights) == 9


def test_straight_never_contains_joker():
    hand = ["2", "3", "4", "5", "6", "SJ", "BJ"]

    for move in generate_candidates(hand):
        info = analyze_cards(move)

        if info["type"] in (TYPE_STRAIGHT, TYPE_FLUSH_STRAIGHT):
            ranks = {rank_of(card) for card in move}
            assert "SJ" not in ranks and "BJ" not in ranks


def test_four_jokers_never_played_together():
    hand = ["SJ", "SJ", "BJ", "BJ"]

    for move in generate_candidates(hand):
        assert len(move) <= 2


def test_triple_pair_is_generated():
    hand = ["3", "3", "3", "2", "2", "7"]

    candidates = generate_candidates(hand)

    assert ["3", "3", "3", "2", "2"] in candidates


def test_triple_pair_with_single_is_not_generated():
    hand = ["3", "3", "3", "7"]

    for move in generate_candidates(hand):
        assert not (len(move) == 4 and analyze_cards(move) is None)


def test_flush_straight_is_generated():
    hand = [("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7")]

    candidates = generate_candidates(hand)
    types = {analyze_cards(move)["type"] for move in candidates}

    assert TYPE_FLUSH_STRAIGHT in types


def test_legal_moves_filters_by_previous():
    hand = ["3", "5", "5"]

    assert legal_moves(hand, ["4"]) == [["5"]]
    assert legal_moves(hand, ["6"]) == []


def test_legal_moves_allows_bomb_over_normal():
    hand = ["3", "9", "9", "9", "9"]

    responses = legal_moves(hand, ["A"])

    assert responses == [["9", "9", "9", "9"]]


def test_legal_moves_respects_level():
    """打 2 时，2 能压 A；不打 2 时不能。"""
    hand = ["2"]

    assert legal_moves(hand, ["A"], level="2") == [["2"]]
    assert legal_moves(hand, ["A"]) == []


def test_bomb_candidates_present_for_four_of_a_kind():
    hand = ["8", "8", "8", "8", "3"]

    bombs = [
        move for move in generate_candidates(hand)
        if analyze_cards(move)["type"] == TYPE_BOMB
    ]

    assert bombs == [["8", "8", "8", "8"]]


def test_candidate_count_is_reasonable():
    """27 张手牌的候选数量必须可控，否则训练和推理都会崩。"""
    from game_engine.game_state import GameState

    game = GameState.new_game(seed=42)
    candidates = generate_candidates(game.hands[0])

    assert 1 <= len(candidates) <= 800


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_legal_move_can_be_played(seed):
    """生成的每个候选都必须能被引擎接受，不能有「生成了但出不去」的动作。"""
    from game_engine.game_state import GameState

    game = GameState.new_game(seed=seed)

    for move in game.get_legal_moves(0):
        cards = list(move)
        # 只验证在手里 + 牌型合法，不真的出牌
        assert Counter(cards) <= Counter(game.hands[0])
        assert analyze_cards(cards) is not None
