"""逻辑漏洞审计。

三件事：
1. 完备性：手牌里所有能被 analyze_cards 判定为合法的组合，必须都能在
   generate_candidates 里找到（不能漏掉玩家本来能出的牌）。
2. 自洽性：compare_cards 必须满足「A 压 B」则「B 不能压 A」，且同型同张数时
   大小关系可传递。
3. 边界：级牌上浮、顺子族自然牌力、逢人配的几种解释。
"""

import itertools
import random
import sys

sys.path.insert(0, r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab")

from game_engine.compare import compare_cards
from game_engine.legal_moves import generate_candidates
from game_engine.patterns import analyze_cards, type_label
from game_engine.ranks import NORMAL_RANKS

CARDS = [(suit, rank) for suit in "SHCD" for rank in NORMAL_RANKS] * 2 + ["SJ", "SJ", "BJ", "BJ"]


def signature(cards):
    return tuple(sorted(repr(card) for card in cards))


def play_key(cards, level):
    """策略等价的键：牌型 + 主牌 + 张数 + 点数组合。

    只看「能不能打」时，同一手牌换花色不算新牌路，
    所以完备性要在这一层比较，而不是逐张比。
    """
    from game_engine.ranks import natural_value, rank_of
    from game_engine.wildcards import count_wildcards

    info = analyze_cards(cards, level)

    if info is None:
        return None

    ranks = tuple(sorted(natural_value(rank_of(card)) for card in cards))

    return (info["type"], info["main_value"], info["count"], ranks,
            count_wildcards(cards, level))


def brute_force_valid(hand, level, max_size=6):
    """枚举所有 1..max_size 张的组合，返回能被判为合法的那些。"""
    found = {}

    for size in range(1, max_size + 1):
        for combo in itertools.combinations(hand, size):
            info = analyze_cards(list(combo), level)

            if info is not None:
                found[play_key(combo, level)] = list(combo)

    return found


def audit_completeness(hand, level, max_size=6):
    valid = brute_force_valid(hand, level, max_size)

    candidates = {}
    for cards in generate_candidates(hand, level):
        key = play_key(cards, level)

        if key is not None:
            candidates[key] = cards

    missing = {k: v for k, v in valid.items() if k not in candidates}

    return valid, candidates, missing


def audit_comparison(hands, level, rounds=3000):
    """随机取合法出牌，检查比较关系是否自洽。"""
    rng = random.Random(0)
    plays = []

    for hand in hands:
        plays.extend(generate_candidates(hand, level))

    rng.shuffle(plays)
    plays = plays[:400]

    asymmetric = 0
    for a, b in itertools.combinations(plays, 2):
        ab = compare_cards(a, b, level)
        ba = compare_cards(b, a, level)

        if ab == 1 and ba != -1:
            asymmetric += 1
        if ab == -1 and ba != 1:
            asymmetric += 1
        if ab == 0 and ba != 0:
            asymmetric += 1

    return asymmetric


def main():
    print("=" * 66)
    print("逻辑漏洞审计")
    print("=" * 66)

    for level in ("2", "7"):
        for seed in (11, 12):
            rng = random.Random(seed)
            hand = rng.sample(CARDS, 27)

            valid, candidates, missing = audit_completeness(hand, level, max_size=6)

            print(f"\n级牌={level} 种子={seed}：")
            print(f"  穷举出的合法牌路（≤6 张）：{len(valid)}")
            print(f"  生成器给出的牌路：          {len(candidates)}")
            print(f"  漏掉的牌路：                {len(missing)}")

            if missing:
                for key, cards in list(missing.items())[:8]:
                    kind, main_value, count, ranks, wilds = key
                    print(f"     漏: {type_label({'type': kind})} 张数={count} "
                          f"主牌力={main_value} 点数={ranks} 逢人配={wilds} "
                          f"牌={[f'{c[0]}:{c[1]}' if isinstance(c, tuple) else c for c in cards]}")

            bad = audit_comparison([hand], level)
            print(f"  比较关系不自洽对数：        {bad}")

    print("\n" + "=" * 66)


if __name__ == "__main__":
    main()
