"""逢人配（红桃级牌万能牌）的纯函数工具。

规则依据（2026-11-02 项目负责人确认）：

* 花色为 ``"H"`` 且点数等于本局级牌（level）的牌就是「逢人配」。
  两副牌最多 2 张；level 为 None 时不存在逢人配。
* 逢人配可以当作**除大小王之外**的任意一张牌：点数、花色都可变。
* 单独出时按级牌本身算（单张，牌力 15）。
* 参与牌型时也可以代替任意牌；顺子 / 连对 / 连续飞机中的级牌
  按自然牌力计算（已确定，不要改）。

本模块只放**纯函数**，不导入 patterns / legal_moves，避免循环导入。
牌型解释的枚举在 patterns.py 与 legal_moves.py 里完成，这里只提供
识别、拆分、缺口计算与可行拆分枚举等可复用的基础工具。
"""

from game_engine.ranks import (
    NORMAL_RANKS,
    is_joker,
    rank_of,
    suit_of,
    value_to_rank,
    windows,
)

# 逢人配固定是红桃
WILDCARD_SUIT = "H"

# 逢人配可以变成的点数：除大小王之外的全部普通点数
WILDCARD_RANKS = NORMAL_RANKS


def is_wildcard(card, level=None):
    """这张牌是否是逢人配（红桃级牌）。

    level 为 None 时永远返回 False（无级牌模式没有万能牌）。

    负责人 2026-11-03 确认的用法：

    * 打 2 时，红桃 2 是逢人配；打 7 时，红桃 7 是逢人配。
    * 可以当作除大小王之外的任意一张牌（通常用于凑同花顺等缺一张的情形）。
    * **也可以「就当自己那张牌」用**：红桃 2 + 黑桃 2 可以是一对 2。
    * 在顺子 / 连对 / 连续飞机里，它按**自然牌力**参与
      （打 7 时，红桃 7 在 5-6-7-8-9 里就是 7，不是级牌）。
    """
    if level is None:
        return False

    return suit_of(card) == WILDCARD_SUIT and rank_of(card) == level


def split_wildcards(cards, level=None):
    """把一组牌拆成 ``(逢人配列表, 其余牌列表)``，保持原有顺序。"""
    if level is None:
        return [], list(cards)

    wildcards = []
    others = []

    for card in cards:
        if is_wildcard(card, level):
            wildcards.append(card)
        else:
            others.append(card)

    return wildcards, others


def count_wildcards(cards, level=None):
    """一组牌里逢人配的张数。"""
    wildcards, _ = split_wildcards(cards, level)
    return len(wildcards)


def group_by_rank(cards):
    """按点数把牌分组；组内顺序与输入顺序一致。"""
    groups = {}

    for card in cards:
        groups.setdefault(rank_of(card), []).append(card)

    return groups


def rank_counts(cards):
    """点数 -> 张数。"""
    counts = {}

    for card in cards:
        rank = rank_of(card)
        counts[rank] = counts.get(rank, 0) + 1

    return counts


def is_playable_rank(rank):
    """逢人配能否变成这个点数（大小王不行）。"""
    return rank in WILDCARD_RANKS


def fill_splits(available, need, wildcard_count):
    """枚举「真实牌张数 + 万能牌张数 = need」的所有可行拆分。

    返回 ``[(real_count, wild_count), ...]``，按 real_count 升序。
    available 是手头该点数的真实张数；wildcard_count 是可用万能牌总数。
    """
    if need <= 0:
        return []

    min_real = max(0, need - wildcard_count)
    max_real = min(available, need)

    return [
        (real_count, need - real_count)
        for real_count in range(min_real, max_real + 1)
    ]


def window_deficit(window, groups, need):
    """连续牌型窗口的缺口：每个点数要 need 张，真实牌不够的差值之和。

    window 是自然牌力元组（见 ranks.windows），groups 是**不含万能牌**的
    真实牌分组字典。缺口即至少需要几张逢人配才能补满这个窗口。
    """
    deficit = 0

    for value in window:
        rank = value_to_rank(value)
        available = len(groups.get(rank, []))
        deficit += max(0, need - available)

    return deficit


def sequence_rank_windows(length):
    """长度为 length 的连续点数窗口（点数形式，而不是自然牌力）。"""
    return tuple(
        tuple(value_to_rank(value) for value in window)
        for window in windows(length)
    )


def joker_ranks_in(cards):
    """一组牌里出现的大小王点数列表。"""
    return [rank_of(card) for card in cards if is_joker(rank_of(card))]
