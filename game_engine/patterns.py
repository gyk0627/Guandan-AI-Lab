"""掼蛋牌型识别。

规则依据（2026-11-02 项目负责人确认）：

* 单张 / 对子 / 三张 / 三带二（单组三张带一对）。
* 顺子：恰好 5 张连续，**可以含 2（2 只当最小的一张）**，**不含大小王**；
  A2345 不算顺子。
* 连对（木板）：**恰好 3 对**连续，可以含 2，不含大小王；张数必须相同才能互压，
  按最大的一对比较。2 对、4 对及以上都不合法。
* 连续飞机（钢板）：**恰好 2 组**连续三张。不允许「连续飞机带多个对子」
  （3334445566 非法），3 组及以上也不合法。
* 同花顺：5 张同花色顺子。
* 炸弹：4 至 8 张同点数。
* 四王炸**不存在**（SJ SJ BJ BJ 非法），八张炸弹最大。

牌型用稳定的英文 id 表示（不是中文），因为中文名以前导致编码器匹配失败。
"""

from collections import Counter

from game_engine.ranks import (
    NORMAL_RANKS,
    STRAIGHT_WINDOWS,
    is_consecutive,
    is_joker,
    natural_value,
    rank_of,
    rank_value,
    suit_of,
    value_to_rank,
    windows,
)
from game_engine.wildcards import (
    WILDCARD_RANKS,
    rank_counts,
    split_wildcards,
)

# ---------------------------------------------------------------- 牌型 id
TYPE_SINGLE = "single"
TYPE_PAIR = "pair"
TYPE_TRIPLE = "triple"
TYPE_TRIPLE_PAIR = "triple_pair"
TYPE_STRAIGHT = "straight"
TYPE_FLUSH_STRAIGHT = "flush_straight"
TYPE_PAIR_CHAIN = "pair_chain"
TYPE_PLANE = "plane"
TYPE_BOMB = "bomb"

# 顺序固定，编码器按这个顺序铺 one-hot，不要随意调整
PATTERN_TYPES = (
    TYPE_SINGLE,
    TYPE_PAIR,
    TYPE_TRIPLE,
    TYPE_TRIPLE_PAIR,
    TYPE_STRAIGHT,
    TYPE_FLUSH_STRAIGHT,
    TYPE_PAIR_CHAIN,
    TYPE_PLANE,
    TYPE_BOMB,
)

# 仅用于显示 / 日志
TYPE_LABELS = {
    TYPE_SINGLE: "单张",
    TYPE_PAIR: "对子",
    TYPE_TRIPLE: "三张",
    TYPE_TRIPLE_PAIR: "三带二",
    TYPE_STRAIGHT: "顺子",
    TYPE_FLUSH_STRAIGHT: "同花顺",
    TYPE_PAIR_CHAIN: "连对",
    TYPE_PLANE: "连续飞机",
    TYPE_BOMB: "炸弹",
}

BOMB_MIN = 4
BOMB_MAX = 8
STRAIGHT_LENGTH = 5

# 2026-11-02 负责人确认（覆盖此前「连对最少 2 对」的旧说法）：
# 连对恰好 3 对（木板），连续飞机恰好 2 组（钢板），都没有「更长」的形态。
PAIR_CHAIN_PAIRS = 3
PLANE_TRIPLES = 2

# 一手牌同时能解释成多种牌型时的优先级（数值越大越优先）。
# 待项目负责人确认：本项目规定取「炸弹 > 同花顺 > 连续飞机 > 连对 >
# 顺子 > 三带二 > 三张 > 对子 > 单张」中最高的一种解释。
TYPE_PRIORITY = {
    TYPE_SINGLE: 1,
    TYPE_PAIR: 2,
    TYPE_TRIPLE: 3,
    TYPE_TRIPLE_PAIR: 4,
    TYPE_STRAIGHT: 5,
    TYPE_PAIR_CHAIN: 6,
    TYPE_PLANE: 7,
    TYPE_FLUSH_STRAIGHT: 8,
    TYPE_BOMB: 9,
}


def type_label(info):
    """牌型的可读名称。"""
    if info is None:
        return "不合法"
    return TYPE_LABELS.get(info["type"], info["type"])


def _is_flush(cards):
    """五张牌是否同花色。大小王没有花色，必然不算。"""
    suits = {suit_of(card) for card in cards}
    return len(suits) == 1 and None not in suits


def _build(cards, pattern_type, main_rank, level, sequence=False):
    """组装牌型结果。

    sequence=True 的牌型（顺子 / 连对 / 连续飞机）按**自然牌力**比较：
    级牌在这些牌型里就是它本来的点数。
    其余牌型（单张 / 对子 / 三张 / 三带二 / 炸弹）按含级牌上浮的牌力比较。
    """
    return {
        "type": pattern_type,
        "count": len(cards),
        "size": len({rank_of(card) for card in cards}),
        "main_rank": main_rank,
        "main_value": (
            natural_value(main_rank)
            if sequence
            else rank_value(main_rank, level)
        ),
        "cards": list(cards),
        "level": level,
    }


def analyze_cards(cards, level=None):
    """识别牌型。无法识别时返回 None。

    cards 可以是 ("S", "3") 元组，也可以是 "3" / "SJ" 字符串。
    level 表示本局打几（"2".."A"），None 表示无级牌模式。

    含逢人配（红桃级牌）时，先剥离万能牌，再枚举它们能补成的牌型。
    若同一手牌能组成多种牌型，按 ``TYPE_PRIORITY`` 返回优先级最高的一种
    （炸弹 > 同花顺 > 连续飞机 > 连对 > 顺子 > 三带二 > 三张 > 对子 >
    单张）。该取舍待项目负责人确认。
    """
    if not cards:
        return None

    wildcards, others = split_wildcards(cards, level)

    if not wildcards:
        return _analyze_normal(cards, level)

    return _analyze_with_wildcards(cards, wildcards, others, level)


def _analyze_normal(cards, level=None):
    """不含逢人配时的牌型识别（原有逻辑，保持行为不变）。"""
    number = len(cards)
    ranks = [rank_of(card) for card in cards]

    try:
        values = [natural_value(rank) for rank in ranks]
    except KeyError:
        return None  # 出现无法识别的点数

    counts = Counter(ranks)
    distinct = len(counts)

    # 连对 / 连续飞机要按「不同点数」判断连续，不能带重复点数
    unique_values = [natural_value(rank) for rank in counts]

    # 单张
    if number == 1:
        return _build(cards, TYPE_SINGLE, ranks[0], level)

    # 对子
    if number == 2 and distinct == 1:
        return _build(cards, TYPE_PAIR, ranks[0], level)

    # 三张
    if number == 3 and distinct == 1:
        return _build(cards, TYPE_TRIPLE, ranks[0], level)

    # 炸弹：4 至 8 张同点数
    if BOMB_MIN <= number <= BOMB_MAX and distinct == 1:
        return _build(cards, TYPE_BOMB, ranks[0], level)

    has_joker = any(is_joker(rank) for rank in ranks)

    # 顺子 / 同花顺：五张互不相同、连续、不含大小王
    if (
        number == STRAIGHT_LENGTH
        and distinct == STRAIGHT_LENGTH
        and not has_joker
        and is_consecutive(values)
    ):
        main_rank = max(ranks, key=natural_value)

        if _is_flush(cards):
            return _build(
                cards, TYPE_FLUSH_STRAIGHT, main_rank, level, sequence=True
            )

        return _build(cards, TYPE_STRAIGHT, main_rank, level, sequence=True)

    # 三带二：三张 + 一对（单组，不带多个对子）
    if number == 5 and sorted(counts.values()) == [2, 3]:
        main_rank = next(
            rank
            for rank, count in counts.items()
            if count == 3
        )
        return _build(cards, TYPE_TRIPLE_PAIR, main_rank, level)

    # 连对（木板）：恰好 3 对连续，不含大小王（可以含 2）
    if (
        number == PAIR_CHAIN_PAIRS * 2
        and not has_joker
        and all(count == 2 for count in counts.values())
        and is_consecutive(unique_values)
    ):
        main_rank = max(ranks, key=natural_value)
        return _build(cards, TYPE_PAIR_CHAIN, main_rank, level, sequence=True)

    # 连续飞机（钢板）：恰好 2 组连续三张，不含大小王
    if (
        number == PLANE_TRIPLES * 3
        and not has_joker
        and all(count == 3 for count in counts.values())
        and is_consecutive(unique_values)
    ):
        main_rank = max(ranks, key=natural_value)
        return _build(cards, TYPE_PLANE, main_rank, level, sequence=True)

    return None


def _analyze_with_wildcards(cards, wildcards, others, level):
    """含逢人配时的牌型识别。

    思路：真实牌（不含万能牌）必须落在目标牌型允许的点数集合里，缺口由
    万能牌补齐；万能牌不能变成大小王，所以真实牌里出现王时只剩「三带二」
    一种可能（王整体当三张或一对）。

    同一手牌可能有多种解释，统一收集到 ``candidates`` 后按
    ``TYPE_PRIORITY`` 取最强的一种；同种牌型取主牌牌力最大的一种。
    """
    number = len(cards)
    wildcard_count = len(wildcards)

    # 万能牌不能变成大小王。真实牌里出现王时，唯一还能成立的是
    # 「三带二」：王整体当三张或一对，其余由真实牌 + 万能牌补齐。
    joker_cards = [card for card in others if is_joker(rank_of(card))]

    if joker_cards:
        return _analyze_joker_triple_pair(
            cards, wildcards, joker_cards, others, level
        )

    try:
        values = [natural_value(rank_of(card)) for card in others]
    except KeyError:
        return None

    counts = rank_counts(others)
    real_rank_count = len(counts)

    candidates = []

    def consider(pattern_type, main_rank, sequence=False):
        info = _build(cards, pattern_type, main_rank, level, sequence=sequence)
        candidates.append(
            (TYPE_PRIORITY[pattern_type], info["main_value"], info)
        )

    # 单张：万能牌单独出时按级牌本身算（牌力 15）
    if number == 1:
        return _build(cards, TYPE_SINGLE, level, level)

    # 对子 / 三张 / 炸弹：真实牌必须同点数（或全部由万能牌组成）
    if real_rank_count <= 1:
        if real_rank_count == 1:
            main_rank = next(iter(counts))
        else:
            # 全部由万能牌组成时，取牌力最高的普通点数（即级牌）
            main_rank = max(
                WILDCARD_RANKS,
                key=lambda rank: rank_value(rank, level),
            )

        if number == 2:
            consider(TYPE_PAIR, main_rank)
        elif number == 3:
            consider(TYPE_TRIPLE, main_rank)
        elif BOMB_MIN <= number <= BOMB_MAX:
            consider(TYPE_BOMB, main_rank)

    # 顺子 / 同花顺：真实牌点数互不相同，并且落在同一个连续窗口里
    if number == STRAIGHT_LENGTH and all(
        count == 1 for count in counts.values()
    ):
        real_values = set(values)

        # 万能牌的花色可变：只要真实牌同花色（或没有真实牌）就能凑同花顺
        suits = {suit_of(card) for card in others}
        flush_possible = len(suits) <= 1 and None not in suits

        for window in STRAIGHT_WINDOWS:
            if not real_values <= set(window):
                continue

            missing = [value for value in window if value not in real_values]

            if len(missing) != wildcard_count:
                continue

            main_rank = value_to_rank(window[-1])

            if flush_possible:
                consider(TYPE_FLUSH_STRAIGHT, main_rank, sequence=True)

            consider(TYPE_STRAIGHT, main_rank, sequence=True)

    # 三带二：真实牌必须全部落在「三张点数 + 对子点数」这两个点数里
    if number == 5 and real_rank_count <= 2:
        for triple_rank in WILDCARD_RANKS:
            triple_real = counts.get(triple_rank, 0)

            if triple_real > 3:
                continue

            triple_need = 3 - triple_real

            if triple_need > wildcard_count:
                continue

            for pair_rank in WILDCARD_RANKS:
                if pair_rank == triple_rank:
                    continue

                pair_real = counts.get(pair_rank, 0)

                if pair_real > 2:
                    continue

                pair_need = 2 - pair_real

                if pair_need > wildcard_count:
                    continue

                if triple_need + pair_need != wildcard_count:
                    continue

                if set(counts) - {triple_rank, pair_rank}:
                    continue

                consider(TYPE_TRIPLE_PAIR, triple_rank)

    # 连对（木板）：恰好 3 对，真实牌每个点数最多 2 张
    if (
        number == PAIR_CHAIN_PAIRS * 2
        and all(count <= 2 for count in counts.values())
    ):
        length = PAIR_CHAIN_PAIRS

        real_values = set(values)

        for window in windows(length):
            if not real_values <= set(window):
                continue

            main_rank = value_to_rank(window[-1])
            consider(TYPE_PAIR_CHAIN, main_rank, sequence=True)

    # 连续飞机（钢板）：恰好 2 组，真实牌每个点数最多 3 张
    if (
        number == PLANE_TRIPLES * 3
        and all(count <= 3 for count in counts.values())
    ):
        length = PLANE_TRIPLES

        real_values = set(values)

        for window in windows(length):
            if not real_values <= set(window):
                continue

            main_rank = value_to_rank(window[-1])
            consider(TYPE_PLANE, main_rank, sequence=True)

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    return candidates[0][2]


def _analyze_joker_triple_pair(cards, wildcards, joker_cards, others, level):
    """含王 + 逢人配时唯一可能的牌型：三带二。

    万能牌不能变成王，所以王不可能参与顺子 / 连对 / 连续飞机 / 炸弹；
    王只能整体作为「三张」或「一对」出现在三带二里。

    * 2 张同种王：王当对子，其余由真实牌 + 万能牌凑三张。
    * 3 张同种王：王当三张，其余由真实牌 + 万能牌凑一对。
      （两副牌实际只有 2 张同种王，这里只做纯函数层面的兼容。）
    """
    if len(cards) != 5:
        return None

    joker_ranks = {rank_of(card) for card in joker_cards}

    if len(joker_ranks) != 1:
        return None  # 小王 + 大王凑不成同点数

    joker_rank = next(iter(joker_ranks))
    joker_count = len(joker_cards)

    non_joker = [
        card for card in others
        if not is_joker(rank_of(card))
    ]

    try:
        for card in non_joker:
            natural_value(rank_of(card))
    except KeyError:
        return None

    counts = rank_counts(non_joker)

    if len(counts) > 1:
        return None

    if joker_count == 2:
        # 王当对子，其余凑三张
        if any(count > 3 for count in counts.values()):
            return None

        if len(non_joker) + len(wildcards) != 3:
            return None

        if counts:
            triple_rank = next(iter(counts))
        else:
            # 三张全部由万能牌组成时，取牌力最高的普通点数（即级牌）
            triple_rank = max(
                WILDCARD_RANKS,
                key=lambda rank: rank_value(rank, level),
            )

        return _build(cards, TYPE_TRIPLE_PAIR, triple_rank, level)

    if joker_count == 3:
        # 王当三张，其余凑一对
        if any(count > 2 for count in counts.values()):
            return None

        if len(non_joker) + len(wildcards) != 2:
            return None

        return _build(cards, TYPE_TRIPLE_PAIR, joker_rank, level)

    return None


def is_valid_play(cards, level=None):
    """这手牌是否构成合法牌型。"""
    return analyze_cards(cards, level) is not None


def is_sequence_type(pattern_type):
    """该牌型是否按自然牌力比较（顺子族）。"""
    return pattern_type in (
        TYPE_STRAIGHT,
        TYPE_FLUSH_STRAIGHT,
        TYPE_PAIR_CHAIN,
        TYPE_PLANE,
    )


def is_bomb_like(info):
    """炸弹和同花顺都属于「炸弹类」，可以压普通牌型。"""
    return info is not None and info["type"] in (TYPE_BOMB, TYPE_FLUSH_STRAIGHT)
