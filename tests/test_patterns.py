"""牌型识别测试。对应规则纸上逐条确认过的内容。"""

import pytest

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
    is_bomb_like,
    type_label,
)

FLUSH_3_7 = [("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7")]
MIXED_3_7 = [("S", "3"), ("H", "4"), ("S", "5"), ("S", "6"), ("S", "7")]


@pytest.mark.parametrize(
    "cards,expected",
    [
        # 基础牌型
        (["3"], TYPE_SINGLE),
        (["3", "3"], TYPE_PAIR),
        (["3", "3", "3"], TYPE_TRIPLE),
        (["3", "3", "3", "3"], TYPE_BOMB),
        (["3"] * 5, TYPE_BOMB),
        (["3"] * 6, TYPE_BOMB),
        (["3"] * 7, TYPE_BOMB),
        (["3"] * 8, TYPE_BOMB),
        # 三带二：单组三张带一对
        (["3", "3", "3", "2", "2"], TYPE_TRIPLE_PAIR),
        (["K", "K", "K", "A", "A"], TYPE_TRIPLE_PAIR),
        # 顺子：可含 2（只能当最小），不含王
        (["2", "3", "4", "5", "6"], TYPE_STRAIGHT),
        (["3", "4", "5", "6", "7"], TYPE_STRAIGHT),
        (["10", "J", "Q", "K", "A"], TYPE_STRAIGHT),
        (MIXED_3_7, TYPE_STRAIGHT),
        # 同花顺
        (FLUSH_3_7, TYPE_FLUSH_STRAIGHT),
        # 连对（木板）：恰好 3 对，可含 2，不含王
        (["2", "2", "3", "3", "4", "4"], TYPE_PAIR_CHAIN),
        (["3", "3", "4", "4", "5", "5"], TYPE_PAIR_CHAIN),
        (["10", "10", "J", "J", "Q", "Q"], TYPE_PAIR_CHAIN),
        # 连续飞机（钢板）：恰好 2 组
        (["3", "3", "3", "4", "4", "4"], TYPE_PLANE),
    ],
)
def test_valid_patterns(cards, expected):
    info = analyze_cards(cards)

    assert info is not None, f"{cards} 应被识别为合法牌型"
    assert info["type"] == expected
    assert info["count"] == len(cards)


@pytest.mark.parametrize(
    "cards",
    [
        # 空
        [],
        # 炸弹最多 8 张
        ["3"] * 9,
        # 三带单张 / 三带散牌 都不合法
        ["3", "3", "3", "2"],
        ["3", "3", "3", "4", "5"],
        # 顺子不能接 2 在 A 之后，A2345 也不成立
        ["J", "Q", "K", "A", "2"],
        ["A", "2", "3", "4", "5"],
        # 顺子不含大小王
        ["Q", "K", "A", "2", "SJ"],
        ["K", "A", "2", "SJ", "BJ"],
        ["3", "4", "5", "SJ", "BJ"],
        # 四王炸不存在
        ["SJ", "SJ", "BJ", "BJ"],
        # 飞机必须连续
        ["3", "3", "3", "5", "5", "5"],
        # 不许「飞机带对」
        ["3", "3", "3", "4", "4", "4", "5", "5"],
        ["3", "3", "3", "4", "4", "4", "5", "5", "6", "6"],
        ["3", "3", "3", "4", "4", "4", "5", "5", "5",
         "6", "6", "7", "7", "8", "8"],
        # 连对不能带王
        ["2", "2", "SJ", "SJ"],
        # 连对必须连续、且每点数两张
        ["3", "3", "4", "4", "6", "6"],
        ["3", "3", "4", "4", "5"],
        # 连对恰好 3 对：2 对、4 对、5 对都非法
        ["2", "2", "3", "3"],
        ["3", "3", "4", "4", "5", "5", "6", "6"],
        ["10", "10", "J", "J", "Q", "Q", "K", "K", "A", "A"],
        # 连续飞机恰好 2 组：3 组非法
        ["3", "3", "3", "4", "4", "4", "5", "5", "5"],
    ],
)
def test_invalid_patterns(cards):
    assert analyze_cards(cards) is None


def test_single_ace_beats_two():
    """2 是最小的：单张 2 比单张 3 小。"""
    two = analyze_cards(["2"])
    three = analyze_cards(["3"])
    ace = analyze_cards(["A"])

    assert two["main_value"] < three["main_value"]
    assert ace["main_value"] > three["main_value"]


def test_straight_main_rank_is_highest_card():
    low = analyze_cards(["2", "3", "4", "5", "6"])
    high = analyze_cards(["10", "J", "Q", "K", "A"])

    assert low["main_rank"] == "6"
    assert low["main_value"] == 6
    assert high["main_rank"] == "A"
    assert high["main_value"] == 14
    assert high["main_value"] > low["main_value"]


def test_pair_chain_main_rank_is_highest_pair():
    info = analyze_cards(["3", "3", "4", "4", "5", "5"])

    assert info["main_rank"] == "5"
    assert info["main_value"] == 5


def test_triple_pair_main_rank_is_the_triple():
    """三带二只看三张，对子不参与比较。"""
    small_pair = analyze_cards(["3", "3", "3", "2", "2"])
    big_pair = analyze_cards(["3", "3", "3", "A", "A"])

    assert small_pair["main_rank"] == "3"
    assert small_pair["main_value"] == big_pair["main_value"]


def test_flush_straight_requires_same_suit():
    assert analyze_cards(FLUSH_3_7)["type"] == TYPE_FLUSH_STRAIGHT
    assert analyze_cards(MIXED_3_7)["type"] == TYPE_STRAIGHT


def test_level_card_floats_but_only_outside_sequences():
    """打 2 时 2 是级牌：单张上浮到 15，但在顺子里仍按自然点数 2。"""
    single = analyze_cards(["2"], level="2")
    straight = analyze_cards(["2", "3", "4", "5", "6"], level="2")

    assert single["main_value"] == 15
    assert straight["main_value"] == 6  # 待确认：级牌在顺子中按自然牌力


def test_level_card_in_pair_and_bomb():
    pair = analyze_cards(["2", "2"], level="2")
    bomb = analyze_cards(["2"] * 4, level="2")

    assert pair["main_value"] == 15
    assert bomb["main_value"] == 15


def test_joker_pair_is_valid():
    """两张小王可以当对子出（两副牌各有一张）。"""
    info = analyze_cards(["SJ", "SJ"])

    assert info["type"] == TYPE_PAIR
    assert info["main_value"] == 16


def test_is_bomb_like():
    assert is_bomb_like(analyze_cards(["3"] * 4))
    assert is_bomb_like(analyze_cards(FLUSH_3_7))
    assert not is_bomb_like(analyze_cards(["3", "4", "5", "6", "7"]))
    assert not is_bomb_like(None)


def test_type_label():
    assert type_label(analyze_cards(["3", "3"])) == "对子"
    assert type_label(None) == "不合法"


def test_hundred_cards_bomb_is_invalid():
    assert analyze_cards(["5"] * 8) is not None
    assert analyze_cards(["5"] * 9) is None
