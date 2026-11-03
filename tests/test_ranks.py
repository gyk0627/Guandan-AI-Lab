"""牌点与牌力的唯一真理源测试。"""

import pytest

from game_engine.ranks import (
    BIG_JOKER,
    JOKER_VALUE,
    LEVEL_VALUE,
    NORMAL_RANKS,
    NORMAL_VALUE,
    SMALL_JOKER,
    STRAIGHT_WINDOWS,
    is_consecutive,
    natural_value,
    rank_of,
    rank_value,
    windows,
)


def test_two_is_lowest():
    """2 是最小的（负责人确认：1A）。"""
    assert NORMAL_VALUE["2"] == 2
    assert NORMAL_VALUE["2"] < NORMAL_VALUE["3"]
    assert NORMAL_VALUE["A"] == 14


def test_rank_order_is_ascending():
    values = [NORMAL_VALUE[rank] for rank in NORMAL_RANKS]

    assert values == sorted(values)
    assert values == list(range(2, 15))


def test_jokers_are_above_ace():
    assert JOKER_VALUE[SMALL_JOKER] == 16
    assert JOKER_VALUE[BIG_JOKER] == 17
    assert JOKER_VALUE[SMALL_JOKER] > NORMAL_VALUE["A"]
    assert JOKER_VALUE[BIG_JOKER] > JOKER_VALUE[SMALL_JOKER]


def test_level_floats_between_ace_and_small_joker():
    """打 2 时，2 的牌力上浮到 A 与小王之间。"""
    assert rank_value("2", level="2") == LEVEL_VALUE
    assert NORMAL_VALUE["A"] < LEVEL_VALUE < JOKER_VALUE[SMALL_JOKER]
    # 未启用级牌时保持自然牌力
    assert rank_value("2") == NORMAL_VALUE["2"]
    # 非级牌点数不受影响
    assert rank_value("5", level="2") == NORMAL_VALUE["5"]


def test_without_level_nothing_floats():
    for rank in NORMAL_RANKS:
        assert rank_value(rank) == NORMAL_VALUE[rank]


def test_straight_windows_are_nine():
    """2..A 共 13 个点数，长度 5 的连续窗口是 9 个。"""
    assert len(STRAIGHT_WINDOWS) == 9
    assert STRAIGHT_WINDOWS[0] == (2, 3, 4, 5, 6)
    assert STRAIGHT_WINDOWS[-1] == (10, 11, 12, 13, 14)


def test_a2345_is_not_a_window():
    """A2345 不构成顺子：2 在最低端，A 与 2 不相邻。"""
    assert (14, 2, 3, 4, 5) not in STRAIGHT_WINDOWS
    assert not any(2 in window and 14 in window for window in STRAIGHT_WINDOWS)


def test_windows_length_bounds():
    assert windows(1) == tuple((value,) for value in range(2, 15))
    assert windows(0) == ()
    assert windows(14) == ()
    assert windows(13) == ((2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),)


def test_is_consecutive():
    assert is_consecutive([2, 3, 4, 5, 6])
    assert is_consecutive([14, 13, 12, 11, 10])
    assert not is_consecutive([2, 3, 4, 5, 7])
    assert not is_consecutive([2, 3, 4, 5, 14])


@pytest.mark.parametrize(
    "card,expected",
    [
        (("S", "3"), "3"),
        (("H", "10"), "10"),
        (SMALL_JOKER, SMALL_JOKER),
        ("A", "A"),
        (("D", "2"), "2"),
    ],
)
def test_rank_of(card, expected):
    assert rank_of(card) == expected


def test_natural_value_of_unknown_rank_raises():
    with pytest.raises(KeyError):
        natural_value("X")
