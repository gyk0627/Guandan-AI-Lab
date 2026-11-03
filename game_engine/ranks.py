"""牌点、牌力与序列窗口的**唯一**来源。

规则依据（2026-11-02 项目负责人确认）：

    基础牌力（2 最小）：
        2 < 3 < 4 < 5 < 6 < 7 < 8 < 9 < 10 < J < Q < K < A

    打某一点数时，该点数为「级牌」，牌力临时上浮到 A 之上、小王之下：
        ... < A < 级牌 < 小王 < 大王

    红桃级牌为「逢人配」（万能牌），D1.5 阶段实现。

以前的代码在 patterns.py / players/heuristic.py / training/state_encoder.py
各自维护了一份点数表，改一处漏两处。现在所有模块都必须从这里取。
"""

# 普通点数，按牌力从小到大。2 是最小的。
NORMAL_RANKS = (
    "2", "3", "4", "5", "6", "7", "8", "9",
    "10", "J", "Q", "K", "A",
)

# 普通点数的自然牌力：2 -> 2, 3 -> 3, ..., A -> 14
NORMAL_VALUE = {
    rank: index + 2
    for index, rank in enumerate(NORMAL_RANKS)
}

SMALL_JOKER = "SJ"
BIG_JOKER = "BJ"

JOKER_RANKS = (SMALL_JOKER, BIG_JOKER)

# 大小王的牌力
JOKER_VALUE = {
    SMALL_JOKER: 16,
    BIG_JOKER: 17,
}

# 级牌上浮后的牌力：高于 A(14)，低于小王(16)
LEVEL_VALUE = 15

SUITS = ("S", "H", "C", "D")

# 参与顺子 / 连对 / 连续飞机的点数（不含大小王）
SEQUENCE_RANKS = NORMAL_RANKS

# 顺子 / 连对 / 连续飞机 使用的自然牌力序列：2..14
SEQUENCE_VALUES = tuple(range(2, 15))


def rank_of(card):
    """取出一张牌的点数。既接受 ("S", "3") 也接受 "SJ" / "3"。"""
    if isinstance(card, str):
        return card
    return card[1]


def suit_of(card):
    """取出一张牌的花色；大小王没有花色，返回 None。"""
    if isinstance(card, str):
        return None
    return card[0]


def is_joker(rank):
    return rank in JOKER_VALUE


def natural_value(rank):
    """不考虑级牌上浮的牌力。"""
    if rank in JOKER_VALUE:
        return JOKER_VALUE[rank]
    return NORMAL_VALUE[rank]


def rank_value(rank, level=None):
    """牌力。级牌（level）上浮到 15，其余按自然牌力。

    level 为 "2".."A" 之一；None 表示无级牌模式。
    """
    if level is not None and rank == level:
        return LEVEL_VALUE
    return natural_value(rank)


def is_level(rank, level):
    return level is not None and rank == level


def value_to_rank(value):
    """自然牌力反查点数（仅 2..14）。"""
    return NORMAL_RANKS[value - 2]


def windows(length):
    """返回所有长度为 length 的连续自然牌力窗口。

    length=5 时即为全部合法顺子（2-3-4-5-6 ... 10-J-Q-K-A，共 9 种）。
    A2345 不在这张表里：因为 2 在最低端，A(14) 与 2(2) 不相邻。
    """
    if length < 1 or length > len(SEQUENCE_VALUES):
        return ()
    return tuple(
        SEQUENCE_VALUES[start:start + length]
        for start in range(len(SEQUENCE_VALUES) - length + 1)
    )


# 全部合法顺子（9 种），其余模块直接引用，不要再自己算
STRAIGHT_WINDOWS = windows(5)


def is_consecutive(values):
    """判断一组自然牌力是否严格连续（已排序）。"""
    values = sorted(values)
    return all(
        values[i + 1] - values[i] == 1
        for i in range(len(values) - 1)
    )
