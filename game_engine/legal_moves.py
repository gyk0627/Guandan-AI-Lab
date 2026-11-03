"""合法动作生成。

规则约束（2026-11-02 确认）：

* 顺子恰好 5 张、可含 2、不含王；A2345 不存在（2 在最低端）。
* 连对 ≥2 对、连续、可含 2、不含王。
* 连续飞机 ≥2 组；不允许带多个对子。
* 炸弹 4~8 张同点数；无四王炸。

实现说明：
* 单张 / 对子 / 三张 / 炸弹 / 顺子 / 三带二 会把**花色不同的同点数选择**全部枚举，
  因为保留哪张花色在残局里是有意义的（同花顺、逢人配）。
* 连对 / 连续飞机 的候选只取一个规范选法，否则组合数会爆炸
  （例如 4 张同点 × 6 个连续点数 = 6^6 种花色排列）。
  这一取舍在 D2 重做动作表示时重新评估。
"""

from itertools import combinations, product

from game_engine.compare import can_beat
from game_engine.patterns import (
    PAIR_CHAIN_PAIRS,
    PLANE_TRIPLES,
    analyze_cards,
)
from game_engine.ranks import (
    JOKER_RANKS,
    NORMAL_RANKS,
    STRAIGHT_WINDOWS,
    SUITS,
    rank_of,
    suit_of,
    value_to_rank,
    windows,
)
from game_engine.wildcards import fill_splits, split_wildcards

ALL_RANKS = NORMAL_RANKS + JOKER_RANKS

MAX_BOMB = 8
MAX_CHAIN_LENGTH = len(NORMAL_RANKS)   # 13
MAX_PLANE_LENGTH = 9                   # 27 张手牌最多凑 9 组三张


def _build_patterns():
    """把牌型模板分成「枚举花色」和「只取规范解」两类。"""
    exhaustive = []
    canonical = []

    # 单张 / 对子 / 三张 / 炸弹（4~8 张）
    for rank in ALL_RANKS:
        for count in range(1, MAX_BOMB + 1):
            exhaustive.append(((rank, count),))

    # 顺子：全部 9 种连续窗口
    for window in STRAIGHT_WINDOWS:
        exhaustive.append(
            tuple((value_to_rank(value), 1) for value in window)
        )

    # 三带二：单组三张 + 一对
    for triple_rank in ALL_RANKS:
        for pair_rank in ALL_RANKS:
            if pair_rank == triple_rank:
                continue
            exhaustive.append(((triple_rank, 3), (pair_rank, 2)))

    # 连对（木板）：恰好 3 对
    for window in windows(PAIR_CHAIN_PAIRS):
        canonical.append(
            tuple((value_to_rank(value), 2) for value in window)
        )

    # 连续飞机（钢板）：恰好 2 组
    for window in windows(PLANE_TRIPLES):
        canonical.append(
            tuple((value_to_rank(value), 3) for value in window)
        )

    return exhaustive, canonical


EXHAUSTIVE_PATTERNS, CANONICAL_PATTERNS = _build_patterns()


def _group_hand(hand):
    """按点数把牌分组，组内顺序固定，保证生成结果可复现。"""
    groups = {}

    for card in sorted(hand, key=repr):
        groups.setdefault(rank_of(card), []).append(card)

    return groups


def _signature(cards):
    return tuple(sorted(repr(card) for card in cards))


def _pick_groups(groups, pattern):
    """模板能否被手牌满足；返回每个点数可用的牌列表。"""
    choices = []

    for rank, count in pattern:
        available = groups.get(rank, [])

        if len(available) < count:
            return None

        choices.append(available)

    return choices


def _emit_with_wildcards(add, real_cards, wild_count, wildcard_options):
    """把「真实牌 + wild_count 张万能牌」的所有选法交给 add。"""
    for selected in wildcard_options.get(wild_count, ()):
        add(list(real_cards) + list(selected))


def _emit_sequence(add, available, need, total, wildcard_options):
    """为序列牌型（顺子 / 同花顺 / 连对 / 飞机）枚举真实牌与万能牌的分配。

    available[i] 是第 i 个点数可用的真实牌；need 是每个点数要几张。

    与旧实现的关键区别：旧实现只用万能牌补「完全没有真牌」的点数；
    这里允许万能牌顶替**已经有真牌**的点数——那是有意义的选择。
    例如手里四张 5：用「一张 5 + 逢人配」先打一对 5，留下三张 5 之后打飞机。

    真实牌按点数排序取前若干张（规范解），不再逐一枚举花色，
    否则「每个点数取 0/1/2/3 张」的组合会与花色组合相乘，爆炸。
    """
    for real_counts in product(*[range(0, need + 1) for _ in available]):
        wild_count = sum(need - count for count in real_counts)

        if not 1 <= wild_count <= total:
            continue

        if any(count > len(cards) for count, cards in zip(real_counts, available)):
            continue

        real_cards = []
        for cards, count in zip(available, real_counts):
            real_cards.extend(cards[:count])

        _emit_with_wildcards(add, real_cards, wild_count, wildcard_options)


def _generate_wildcard_candidates(add, groups, wildcards):
    """生成至少含一张逢人配的候选。

    groups 是**不含万能牌**的真实牌按点数分组；wildcards 是逢人配列表。
    候选按牌型骨架生成，最终仍由 analyze_cards 统一判定与去重：

    * 对子 / 三张 / 炸弹：真实张数 + 万能牌张数 = 需求张数即可。
    * 顺子 / 连对 / 连续飞机：每个点数「几张真牌 + 几张万能牌」全组合。
    * 三带二同理；同花顺按每个花色单独计算缺口（万能牌花色可变）。
    """
    total = len(wildcards)

    wildcard_options = {
        count: list(combinations(wildcards, count))
        for count in range(1, total + 1)
    }

    # 对子 / 三张 / 炸弹（同点数）
    for rank in NORMAL_RANKS:
        available = groups.get(rank, [])

        for need in range(2, MAX_BOMB + 1):
            for real_count, wild_count in fill_splits(
                len(available), need, total
            ):
                if wild_count == 0:
                    continue

                for real_cards in combinations(available, real_count):
                    _emit_with_wildcards(
                        add, real_cards, wild_count, wildcard_options
                    )

    # 三带二：三张 + 一对。对子部分允许是真实的大小王对。
    for triple_rank in NORMAL_RANKS:
        triple_available = groups.get(triple_rank, [])

        for pair_rank in ALL_RANKS:
            if pair_rank == triple_rank:
                continue

            pair_available = groups.get(pair_rank, [])
            pair_is_joker = pair_rank in JOKER_RANKS

            triple_splits = fill_splits(len(triple_available), 3, total)
            pair_splits = fill_splits(len(pair_available), 2, total)

            for real_triple, wild_triple in triple_splits:
                for real_pair, wild_pair in pair_splits:
                    wild_count = wild_triple + wild_pair

                    if wild_count < 1 or wild_count > total:
                        continue

                    # 万能牌不能变成大小王，王对必须用真实王
                    if pair_is_joker and real_pair != 2:
                        continue

                    for triple_cards in combinations(
                        triple_available, real_triple
                    ):
                        for pair_cards in combinations(
                            pair_available, real_pair
                        ):
                            _emit_with_wildcards(
                                add,
                                list(triple_cards) + list(pair_cards),
                                wild_count,
                                wildcard_options,
                            )

    # 顺子：每个点数「几张真牌 + 几张万能牌」的全组合
    for window in STRAIGHT_WINDOWS:
        window_ranks = [value_to_rank(value) for value in window]
        _emit_sequence(
            add,
            [groups.get(rank, []) for rank in window_ranks],
            1,
            total,
            wildcard_options,
        )

    # 同花顺：每个花色单独算，万能牌可以变成该花色的任意点数
    for suit in SUITS:
        for window in STRAIGHT_WINDOWS:
            window_ranks = [value_to_rank(value) for value in window]
            available = [
                [card for card in groups.get(rank, []) if suit_of(card) == suit]
                for rank in window_ranks
            ]
            _emit_sequence(add, available, 1, total, wildcard_options)

    # 连对（木板）：恰好 3 对
    for window in windows(PAIR_CHAIN_PAIRS):
        window_ranks = [value_to_rank(value) for value in window]
        _emit_sequence(
            add,
            [groups.get(rank, []) for rank in window_ranks],
            2,
            total,
            wildcard_options,
        )

    # 连续飞机（钢板）：恰好 2 组
    for window in windows(PLANE_TRIPLES):
        window_ranks = [value_to_rank(value) for value in window]
        _emit_sequence(
            add,
            [groups.get(rank, []) for rank in window_ranks],
            3,
            total,
            wildcard_options,
        )


def generate_candidates(hand, level=None):
    """枚举当前手牌能打出的全部不同牌组合。"""
    groups = _group_hand(hand)
    results = {}
    seen = set()

    def add(cards):
        signature = _signature(cards)

        # 先按牌组合去重，再做牌型识别：含逢人配时同一组牌会被多个
        # 牌型骨架重复枚举，提前去重能省掉大量分析开销。
        if signature in seen:
            return

        seen.add(signature)

        info = analyze_cards(cards, level)

        if info is None:
            return

        results[signature] = cards

    # 枚举花色的模板
    for pattern in EXHAUSTIVE_PATTERNS:
        choices = _pick_groups(groups, pattern)

        if choices is None:
            continue

        option_lists = [
            list(combinations(available, count))
            for available, (rank, count) in zip(choices, pattern)
        ]

        for selected in product(*option_lists):
            cards = []
            for group in selected:
                cards.extend(group)
            add(cards)

    # 只取规范解的模板
    for pattern in CANONICAL_PATTERNS:
        choices = _pick_groups(groups, pattern)

        if choices is None:
            continue

        cards = []
        for available, (rank, count) in zip(choices, pattern):
            cards.extend(available[:count])
        add(cards)

    # 逢人配参与的候选
    wildcards, others = split_wildcards(hand, level)

    if wildcards:
        _generate_wildcard_candidates(
            add, _group_hand(others), wildcards
        )

    return list(results.values())


def legal_moves(hand, previous=None, level=None):
    """当前可以出的牌。

    previous 为 None 表示自由领出；否则只保留能压过它的牌。
    注意：不包含「过牌」，过牌由调用方决定。
    """
    candidates = generate_candidates(hand, level)

    if previous is None:
        return candidates

    return [
        candidate
        for candidate in candidates
        if can_beat(candidate, previous, level)
    ]
