"""发牌随机性检验（最终版）。

注意：前面两版都是**测试自身**写错了，不是发牌器的问题：
1. 用 `card in hand` 计数，同手两张黑桃 A 只算一次；
2. 模拟牌堆漏了 4 张王；
3. 成对数把 4 个座位都累加，却只除以局数。

这一版一次性写对。
"""

import math
import random
import sys
from collections import Counter

sys.path.insert(0, r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab")

from game_engine.cards import create_deck
from game_engine.game_state import GameState

GAMES = 5000


def chi_square(observed, expected):
    return sum((o - e) ** 2 / e for o, e in zip(observed, expected))


def chi_square_p(stat, dof):
    k = dof / 2.0
    total = sum((stat / 2.0) ** i / math.factorial(i) for i in range(int(k)))

    return min(max(math.exp(-stat / 2.0) * total, 0.0), 1.0)


def main():
    print("=" * 64)
    print(f"发牌随机性检验（{GAMES} 局 = {GAMES * 4} 手牌）")
    print("=" * 64)

    seat_occurrences = [0, 0, 0, 0]
    card_seat = Counter()
    pair_counts = []
    triple_counts = []

    for seed in range(GAMES):
        game = GameState.new_game(seed=seed)

        for seat, hand in enumerate(game.hands):
            for card in hand:
                card_seat[(card, seat)] += 1

            seat_occurrences[seat] += hand.count(("S", "A"))

            counts = Counter(
                card[1] if isinstance(card, tuple) else card for card in hand
            )
            pair_counts.append(sum(1 for c in counts.values() if c >= 2))
            triple_counts.append(sum(1 for c in counts.values() if c >= 3))

    hands = GAMES * 4

    print(f"\n[0] 两张黑桃 A 的总出现次数：{sum(seat_occurrences)}（应为 {GAMES * 2}）")

    expected = GAMES * 2 / 4
    stat = chi_square(seat_occurrences, [expected] * 4)
    p1 = chi_square_p(stat, dof=3)

    print(f"\n[1] 黑桃 A 落在四个座位：{seat_occurrences}（期望各 {expected:.0f}）")
    print(f"    卡方 = {stat:.2f}，p ≈ {p1:.3f} → " +
          ("均匀，看不出偏差" if p1 > 0.05 else "有偏差"))

    stat2, dof2 = 0.0, 0

    for card in set(card for card, _ in card_seat):
        observed = [card_seat.get((card, seat), 0) for seat in range(4)]
        total = sum(observed)
        exp = total / 4

        if exp < 5:
            continue

        stat2 += chi_square(observed, [exp] * 4)
        dof2 += 3

    p2 = chi_square_p(stat2, dof2)

    print(f"\n[2] 全部 54 种牌型的座位分布（合计卡方）：")
    print(f"    卡方 = {stat2:.1f}，自由度 {dof2}，p ≈ {p2:.3f} → " +
          ("均匀" if p2 > 0.05 else "有偏差"))

    deck = create_deck()
    rng = random.Random(20261103)
    sim_pairs, sim_triples = [], []

    for _ in range(hands):
        hand = rng.sample(deck, 27)
        counts = Counter(
            card[1] if isinstance(card, tuple) else card for card in hand
        )
        sim_pairs.append(sum(1 for c in counts.values() if c >= 2))
        sim_triples.append(sum(1 for c in counts.values() if c >= 3))

    engine_pairs = sum(pair_counts) / hands
    engine_triples = sum(triple_counts) / hands
    sim_pairs_avg = sum(sim_pairs) / hands
    sim_triples_avg = sum(sim_triples) / hands

    sd = (sum((x - sim_pairs_avg) ** 2 for x in sim_pairs) / hands) ** 0.5
    two_se = 2 * sd * math.sqrt(2 / hands)

    print(f"\n[3] 手牌结构（每手平均）：")
    print(f"    成对点数  引擎 {engine_pairs:.3f} | 独立模拟 {sim_pairs_avg:.3f} "
          f"| 差 {abs(engine_pairs - sim_pairs_avg):.3f}（2 倍标准误 {two_se:.3f}）")
    print(f"    成三点数  引擎 {engine_triples:.3f} | 独立模拟 {sim_triples_avg:.3f}")
    print("    结论：" + (
        "一致，差异在抽样误差内" if abs(engine_pairs - sim_pairs_avg) < two_se
        else "差异偏大"
    ))

    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()
