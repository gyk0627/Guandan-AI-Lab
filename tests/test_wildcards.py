"""逢人配（红桃级牌万能牌）测试。

规则依据（2026-11-02 项目负责人确认）：

* 花色为 "H" 且点数 == level 的牌是逢人配，最多 2 张。
* 可以当作**除大小王之外**的任意一张牌（点数、花色都可变）。
* 单独出时按级牌本身算（单张，牌力 15）。
* 一手牌能组成多种牌型时，返回优先级最高的：
  炸弹 > 同花顺 > 连续飞机 > 连对 > 顺子 > 三带二 > 三张 > 对子 > 单张。
  该取舍待项目负责人确认。
"""

import random
import time
from collections import Counter

import pytest

from game_engine.game_state import GameState
from game_engine.legal_moves import generate_candidates, legal_moves
from game_engine.patterns import (
    TYPE_BOMB,
    TYPE_FLUSH_STRAIGHT,
    TYPE_PAIR,
    TYPE_PAIR_CHAIN,
    TYPE_PLANE,
    TYPE_SINGLE,
    TYPE_STRAIGHT,
    TYPE_TRIPLE,
    TYPE_TRIPLE_PAIR,
    analyze_cards,
)
from game_engine.ranks import NORMAL_RANKS, rank_of
from game_engine.wildcards import (
    count_wildcards,
    is_wildcard,
    split_wildcards,
)

LEVEL = "2"
WILD = ("H", "2")
WILD_COPY = ("H", "2")   # 两副牌里各有一张，牌面相同


def card(suit, rank):
    return (suit, rank)


def make_game(hands, level=None, first_player=0):
    """构造一个手牌可控、级牌可控的对局。"""
    game = GameState.new_game(seed=0)

    game.hands = [list(hand) for hand in hands]
    game.current_player = first_player
    game.leader = first_player
    game.level = level

    return game


def signatures(moves):
    return {
        tuple(sorted(repr(card) for card in move))
        for move in moves
    }


# ---------------------------------------------------------------- 识别与拆分
def test_wildcard_identification():
    assert is_wildcard(WILD, LEVEL)
    assert not is_wildcard(WILD, "3")
    assert not is_wildcard(WILD, None)
    # 只有红桃是万能牌
    assert not is_wildcard(card("S", "2"), LEVEL)
    # 只有级牌是万能牌
    assert not is_wildcard(card("H", "3"), LEVEL)
    # 无花色的点数据写不是万能牌
    assert not is_wildcard("2", LEVEL)


def test_split_wildcards_keeps_order():
    cards = [WILD, card("S", "3"), WILD_COPY, card("H", "3")]

    wildcards, others = split_wildcards(cards, LEVEL)

    assert wildcards == [WILD, WILD_COPY]
    assert others == [card("S", "3"), card("H", "3")]
    assert count_wildcards(cards, LEVEL) == 2
    assert count_wildcards(cards, None) == 0


def test_no_wildcard_when_level_is_none():
    """无级牌时红桃 2 只是普通 2。"""
    info = analyze_cards([WILD])

    assert info["type"] == TYPE_SINGLE
    assert info["main_value"] == 2
    assert analyze_cards([WILD, card("S", "3")]) is None


def test_wrong_level_does_not_make_wildcard():
    assert analyze_cards([WILD, card("S", "3")], level="3") is None


# ---------------------------------------------------------------- 单独出
def test_single_wildcard_is_level_single():
    info = analyze_cards([WILD], level=LEVEL)

    assert info["type"] == TYPE_SINGLE
    assert info["main_rank"] == LEVEL
    assert info["main_value"] == 15


# ---------------------------------------------------------------- 同点数牌型
def test_wildcard_plus_one_is_pair():
    info = analyze_cards([WILD, card("S", "3")], level=LEVEL)

    assert info["type"] == TYPE_PAIR
    assert info["main_rank"] == "3"
    assert info["main_value"] == 3


def test_wildcard_plus_two_is_triple():
    info = analyze_cards(
        [WILD, card("S", "3"), card("C", "3")], level=LEVEL
    )

    assert info["type"] == TYPE_TRIPLE
    assert info["main_rank"] == "3"


def test_wildcard_plus_three_is_bomb():
    info = analyze_cards(
        [WILD, card("S", "3"), card("C", "3"), card("D", "3")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_BOMB
    assert info["main_rank"] == "3"


def test_wildcard_can_complete_level_bomb():
    """逢人配可以变成级牌本身：三张 2 + 万能牌 = 四张 2。"""
    info = analyze_cards(
        [WILD, card("S", "2"), card("C", "2"), card("D", "2")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_BOMB
    assert info["main_rank"] == "2"
    assert info["main_value"] == 15


# ---------------------------------------------------------------- 连续牌型
def test_wildcard_completes_straight():
    info = analyze_cards(
        [WILD, card("S", "3"), card("C", "4"), card("D", "5"), card("S", "6")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_STRAIGHT
    # 万能牌当 7 比当 2 更强（3-4-5-6-7 > 2-3-4-5-6）
    assert info["main_rank"] == "7"


def test_wildcard_completes_pair_chain():
    """连对恰好 3 对：万能牌补成 3-4-5 的最后一对。"""
    info = analyze_cards(
        [
            WILD,
            card("S", "3"), card("C", "3"),
            card("S", "4"), card("C", "4"),
            card("S", "5"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_PAIR_CHAIN
    assert info["main_rank"] == "5"


def test_wildcard_completes_triple_pair():
    info = analyze_cards(
        [
            WILD,
            card("S", "3"), card("C", "3"),
            card("S", "4"), card("C", "4"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_TRIPLE_PAIR
    # 万能牌当 4 凑三张 4 更强
    assert info["main_rank"] == "4"


def test_wildcard_triple_with_joker_pair():
    """万能牌可以补三张，王只当对子：3-3-W + 小王对 合法。"""
    info = analyze_cards(
        [WILD, card("S", "3"), card("C", "3"), "SJ", "SJ"],
        level=LEVEL,
    )

    assert info["type"] == TYPE_TRIPLE_PAIR
    assert info["main_rank"] == "3"


def test_wildcard_completes_plane():
    info = analyze_cards(
        [
            WILD,
            card("S", "3"), card("C", "3"), card("D", "3"),
            card("S", "4"), card("C", "4"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_PLANE
    assert info["main_rank"] == "4"


def test_wildcard_completes_flush_straight():
    """黑桃 3/5/6/7 + 万能牌 = 黑桃 3-4-5-6-7 同花顺。"""
    info = analyze_cards(
        [
            WILD,
            card("S", "3"), card("S", "5"),
            card("S", "6"), card("S", "7"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_FLUSH_STRAIGHT
    assert info["main_rank"] == "7"


def test_wildcard_completes_heart_flush_straight():
    info = analyze_cards(
        [
            WILD,
            card("H", "3"), card("H", "4"),
            card("H", "5"), card("H", "6"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_FLUSH_STRAIGHT
    assert info["main_rank"] == "7"


# ---------------------------------------------------------------- 两张万能牌
def test_two_wildcards_make_triple():
    info = analyze_cards([WILD, WILD_COPY, card("S", "3")], level=LEVEL)

    assert info["type"] == TYPE_TRIPLE
    assert info["main_rank"] == "3"


def test_two_wildcards_make_bomb():
    info = analyze_cards(
        [WILD, WILD_COPY, card("S", "3"), card("C", "3")], level=LEVEL
    )

    assert info["type"] == TYPE_BOMB
    assert info["main_rank"] == "3"


def test_two_wildcards_make_straight():
    info = analyze_cards(
        [WILD, WILD_COPY, card("S", "3"), card("C", "4"), card("D", "5")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_STRAIGHT
    assert info["main_rank"] == "7"


def test_two_wildcards_make_flush_straight():
    info = analyze_cards(
        [WILD, WILD_COPY, card("S", "3"), card("S", "4"), card("S", "5")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_FLUSH_STRAIGHT
    assert info["main_rank"] == "7"


def test_two_wildcards_make_pair_chain():
    info = analyze_cards(
        [
            WILD, WILD_COPY,
            card("S", "3"), card("C", "3"),
            card("S", "4"), card("S", "5"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_PAIR_CHAIN
    assert info["main_rank"] == "5"


def test_two_wildcards_pair_uses_level_value():
    """两张万能牌当对子：它们本身就是级牌，按级牌对子算（15，待确认）。"""
    info = analyze_cards([WILD, WILD_COPY], level=LEVEL)

    assert info["type"] == TYPE_PAIR
    assert info["main_rank"] == LEVEL
    assert info["main_value"] == 15


# ---------------------------------------------------------------- 优先级
def test_bomb_interpretation_wins_over_pair_chain():
    """两张万能牌 + 两张 3：既能当 4 张 3 的炸弹，也能当对子。

    连对要 3 对（6 张），4 张牌凑不出来，所以这里只剩炸弹这一种强解释。
    """
    info = analyze_cards(
        [WILD, WILD_COPY, card("S", "3"), card("C", "3")], level=LEVEL
    )

    assert info["type"] == TYPE_BOMB


def test_flush_straight_interpretation_wins_over_straight():
    info = analyze_cards(
        [WILD, card("S", "3"), card("S", "5"), card("S", "6"), card("S", "7")],
        level=LEVEL,
    )

    assert info["type"] == TYPE_FLUSH_STRAIGHT


def test_plane_interpretation_wins_over_pair_chain():
    info = analyze_cards(
        [
            WILD, WILD_COPY,
            card("S", "3"), card("C", "3"),
            card("S", "4"), card("C", "4"),
        ],
        level=LEVEL,
    )

    assert info["type"] == TYPE_PLANE


# ---------------------------------------------------------------- 不能变成王
@pytest.mark.parametrize(
    "cards",
    [
        # 万能牌 + 小王不能当对王
        [WILD, "SJ"],
        [WILD, "BJ"],
        # 不能凑三张王
        [WILD, WILD_COPY, "SJ"],
        [WILD, WILD_COPY, "SJ", "SJ"],
        # 四王炸不存在，更不能靠万能牌凑出来
        [WILD, WILD_COPY, "SJ", "SJ"],
        ["SJ", "SJ", "BJ", WILD],
        # 含王的顺子永远非法
        [WILD, "SJ", card("S", "3"), card("S", "4"), card("S", "5")],
        [WILD, "BJ", card("S", "3"), card("S", "4"), card("S", "5")],
    ],
)
def test_wildcard_cannot_become_joker(cards):
    assert analyze_cards(cards, level=LEVEL) is None


# ---------------------------------------------------------------- 生成覆盖
@pytest.mark.parametrize(
    "hand,expected_type",
    [
        ([WILD, card("S", "3")], TYPE_PAIR),
        ([WILD, card("S", "3"), card("C", "3")], TYPE_TRIPLE),
        (
            [WILD, card("S", "3"), card("C", "3"), card("D", "3")],
            TYPE_BOMB,
        ),
        (
            [
                WILD,
                card("S", "3"), card("C", "4"),
                card("D", "5"), card("S", "6"),
            ],
            TYPE_STRAIGHT,
        ),
        (
            [
                WILD,
                card("S", "3"), card("C", "3"),
                card("S", "4"), card("C", "4"),
                card("S", "5"),
            ],
            TYPE_PAIR_CHAIN,
        ),
        (
            [
                WILD,
                card("S", "3"), card("C", "3"),
                card("S", "4"), card("C", "4"),
            ],
            TYPE_TRIPLE_PAIR,
        ),
        (
            [
                WILD,
                card("S", "3"), card("C", "3"), card("D", "3"),
                card("S", "4"), card("C", "4"),
            ],
            TYPE_PLANE,
        ),
        (
            [
                WILD,
                card("S", "3"), card("S", "5"),
                card("S", "6"), card("S", "7"),
            ],
            TYPE_FLUSH_STRAIGHT,
        ),
        ([WILD, WILD_COPY, card("S", "3")], TYPE_TRIPLE),
        (
            [
                WILD, WILD_COPY,
                card("S", "3"), card("C", "4"), card("D", "5"),
            ],
            TYPE_STRAIGHT,
        ),
        (
            [
                WILD, WILD_COPY,
                card("S", "3"), card("S", "4"), card("S", "5"),
            ],
            TYPE_FLUSH_STRAIGHT,
        ),
    ],
)
def test_generate_candidates_covers_wildcard_patterns(hand, expected_type):
    types = {
        analyze_cards(move, level=LEVEL)["type"]
        for move in generate_candidates(hand, level=LEVEL)
    }

    assert expected_type in types


def test_generate_candidates_contains_wildcard_pair():
    hand = [WILD, card("S", "3")]
    want = signatures([[WILD, card("S", "3")]])

    assert want <= signatures(generate_candidates(hand, level=LEVEL))


def test_legal_moves_can_use_single_wildcard():
    """单张逢人配（牌力 15）能压 K。"""
    hand = [WILD, card("S", "A")]

    responses = legal_moves(hand, ["K"], level=LEVEL)

    assert [WILD] in responses


def test_generated_wildcard_moves_are_all_valid_and_playable():
    """每个候选都必须 analyze 合法，并且能被 GameState.play 真正执行。"""
    hand = [
        WILD,
        card("S", "3"), card("C", "3"), card("D", "3"),
        card("S", "4"), card("C", "4"),
        card("S", "5"),
    ]
    game = make_game([hand, ["3"], ["4"], ["5"]], level=LEVEL)

    candidates = game.get_legal_moves(0)
    assert candidates

    for move in candidates:
        cards = list(move)

        assert analyze_cards(cards, level=LEVEL) is not None
        assert Counter(cards) <= Counter(hand)

        fresh = make_game([hand, ["3"], ["4"], ["5"]], level=LEVEL)
        fresh.play(0, cards)


def test_generated_wildcard_moves_are_unique():
    hand = [WILD, WILD_COPY, card("S", "3"), card("C", "3"), card("S", "4")]

    moves = generate_candidates(hand, level=LEVEL)
    generated = signatures(moves)

    assert len(generated) == len(moves)


def test_generated_sequences_never_contain_jokers():
    hand = [
        WILD, "SJ", "BJ",
        card("S", "3"), card("C", "4"), card("D", "5"), card("S", "6"),
    ]

    for move in generate_candidates(hand, level=LEVEL):
        info = analyze_cards(move, level=LEVEL)

        assert info is not None

        if info["type"] in (TYPE_STRAIGHT, TYPE_FLUSH_STRAIGHT):
            ranks = {rank_of(card) for card in move}
            assert "SJ" not in ranks and "BJ" not in ranks


# ---------------------------------------------------------------- 性能回归
def heavy_wildcard_hand():
    """27 张、含 2 张逢人配的手牌（每种点数两张，压力适中）。"""
    hand = [WILD, WILD_COPY]

    for rank in NORMAL_RANKS:
        if rank == LEVEL:
            continue

        hand.append(card("S", rank))
        hand.append(card("C", rank))

    hand.append(card("D", "2"))

    assert len(hand) == 27
    return hand


def bomb_wildcard_hand():
    """27 张、含 2 张逢人配且炸弹最多的极端手牌。"""
    hand = [WILD, WILD_COPY]

    for rank in ("3", "4", "5"):
        for suit in ("S", "C", "D", "H"):
            hand.append(card(suit, rank))
            hand.append(card(suit, rank))

    hand.append(card("S", "6"))

    assert len(hand) == 27
    return hand


@pytest.mark.parametrize("build_hand", [heavy_wildcard_hand, bomb_wildcard_hand])
def test_wildcard_generation_performance(build_hand):
    """含 2 张逢人配的 27 张手牌：单次生成必须远低于 300ms。

    阈值取 2 倍余量（600ms）防止机器抖动。
    """
    hand = build_hand()

    start = time.perf_counter()
    candidates = generate_candidates(hand, level=LEVEL)
    elapsed = time.perf_counter() - start

    assert candidates

    for move in candidates:
        assert analyze_cards(move, level=LEVEL) is not None

    assert elapsed < 0.6, f"生成耗时 {elapsed * 1000:.1f}ms 超过阈值"


def test_full_game_with_level_performance():
    """整局（打 2，含逢人配）必须远低于 1s，阈值同样给 2 倍余量。"""
    from game_engine.game_state import GameState

    game = GameState.new_game(seed=7, level=LEVEL)
    rng = random.Random(7)

    start = time.perf_counter()

    while not game.game_over:
        player = game.current_player
        moves = game.get_legal_moves(player)

        if moves:
            game.play(player, rng.choice(moves))
        else:
            game.pass_turn(player)

    elapsed = time.perf_counter() - start

    assert len(game.finished_players) == 4
    assert elapsed < 2.0, f"整局耗时 {elapsed:.2f}s 超过阈值"
