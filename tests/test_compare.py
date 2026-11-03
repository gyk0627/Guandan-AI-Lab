"""牌型大小比较测试，重点是炸弹阶梯与 2 的位置。"""

import pytest

from game_engine.compare import can_beat, compare_cards

FLUSH_3_7 = [("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7")]
FLUSH_3_7_HEARTS = [("H", "3"), ("H", "4"), ("H", "5"), ("H", "6"), ("H", "7")]
FLUSH_4_8 = [("S", "4"), ("S", "5"), ("S", "6"), ("S", "7"), ("S", "8")]


def bomb(rank, count):
    return [rank] * count


@pytest.mark.parametrize(
    "lower,higher",
    [
        # 炸弹阶梯：4炸 < 同花顺 < 5炸 < 6炸 < 7炸 < 8炸
        (bomb("A", 4), FLUSH_3_7),
        (FLUSH_3_7, bomb("3", 5)),
        (bomb("3", 5), bomb("3", 6)),
        (bomb("3", 6), bomb("3", 7)),
        (bomb("3", 7), bomb("3", 8)),
        # 同张数炸弹比点数
        (bomb("3", 4), bomb("4", 4)),
        (bomb("K", 5), bomb("A", 5)),
        # 炸弹压任何普通牌型
        (["BJ"], bomb("3", 4)),
        (["3", "4", "5", "6", "7"], bomb("3", 4)),
    ],
)
def test_bomb_ladder(lower, higher):
    assert compare_cards(lower, higher) == -1
    assert compare_cards(higher, lower) == 1
    assert can_beat(higher, lower)
    assert not can_beat(lower, higher)


def test_two_is_smallest_in_comparison():
    assert compare_cards(["2"], ["3"]) == -1
    assert compare_cards(["3"], ["2"]) == 1
    assert compare_cards(["A"], ["2"]) == 1
    assert compare_cards(["SJ"], ["A"]) == 1


def test_with_level_two_becomes_strongest_normal_card():
    """打 2 时，单张 2 能压 A，但压不过小王。"""
    assert compare_cards(["2"], ["A"], level="2") == 1
    assert compare_cards(["A"], ["2"], level="2") == -1
    assert compare_cards(["2"], ["SJ"], level="2") == -1
    # 无级牌模式下 2 仍是最小
    assert compare_cards(["2"], ["A"]) == -1


def test_level_bomb():
    """打 2 时，2222 炸弹大于 AAAA 炸弹。"""
    assert compare_cards(bomb("2", 4), bomb("A", 4), level="2") == 1
    assert compare_cards(bomb("2", 4), bomb("A", 4)) == -1


def test_straight_comparison():
    assert compare_cards(["2", "3", "4", "5", "6"], ["3", "4", "5", "6", "7"]) == -1
    assert compare_cards(
        ["10", "J", "Q", "K", "A"], ["3", "4", "5", "6", "7"]
    ) == 1


def test_pair_chain_comparison():
    """连对（木板）始终 3 对 6 张，只比最大的一对。"""
    assert compare_cards(
        ["2", "2", "3", "3", "4", "4"], ["3", "3", "4", "4", "5", "5"]
    ) == -1
    assert compare_cards(
        ["4", "4", "5", "5", "6", "6"], ["2", "2", "3", "3", "4", "4"]
    ) == 1
    # 主牌相同 → 平手，不能压
    assert compare_cards(
        ["3", "3", "4", "4", "5", "5"], ["3", "3", "4", "4", "5", "5"]
    ) == 0


def test_triple_pair_comparison_ignores_pair():
    assert compare_cards(
        ["3", "3", "3", "2", "2"], ["4", "4", "4", "2", "2"]
    ) == -1
    # 三张相同、对子不同 → 平手，不能压
    assert compare_cards(
        ["3", "3", "3", "2", "2"], ["3", "3", "3", "A", "A"]
    ) == 0


def test_same_flush_straight_is_a_tie():
    assert compare_cards(FLUSH_3_7, FLUSH_3_7_HEARTS) == 0
    # 4-8 同花顺比 3-7 同花顺大
    assert compare_cards(FLUSH_4_8, FLUSH_3_7) == 1
    assert compare_cards(FLUSH_3_7, FLUSH_4_8) == -1


def test_different_types_cannot_beat():
    assert compare_cards(["3", "4", "5", "6", "7"], ["3", "3"]) == 0
    assert compare_cards(["3", "3"], ["3", "4", "5", "6", "7"]) == 0


def test_invalid_cards_raise():
    with pytest.raises(ValueError):
        compare_cards(["3", "3", "3", "2"], ["3", "3"])
    with pytest.raises(ValueError):
        compare_cards(["3", "3"], ["3", "3", "3", "2"])
    with pytest.raises(ValueError):
        compare_cards([], ["3"])
