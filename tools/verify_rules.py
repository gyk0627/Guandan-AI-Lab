import sys

sys.path.insert(0, r"C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab")

from game_engine.game_state import GameState
from game_engine.legal_moves import generate_candidates
from game_engine.patterns import analyze_cards, type_label

cases = [
    ("2 对 3344", ["3", "3", "4", "4"], False),
    ("3 对 334455", ["3", "3", "4", "4", "5", "5"], True),
    ("4 对 TTJJQQKK", ["10", "10", "J", "J", "Q", "Q", "K", "K"], False),
    ("5 对 10JQKA", ["10", "10", "J", "J", "Q", "Q", "K", "K", "A", "A"], False),
    ("2 组 333444", ["3"] * 3 + ["4"] * 3, True),
    ("3 组 333444555", ["3"] * 3 + ["4"] * 3 + ["5"] * 3, False),
    ("4 组 333444555666", ["3"] * 3 + ["4"] * 3 + ["5"] * 3 + ["6"] * 3, False),
]

print("=" * 58)
print("规则校验：连对恰好 3 对 / 连续飞机恰好 2 组")
print("=" * 58)

ok = True
for name, cards, should_be_valid in cases:
    info = analyze_cards(cards)
    valid = info is not None
    mark = "OK " if valid == should_be_valid else "FAIL"
    if valid != should_be_valid:
        ok = False
    print(f"{mark} {name:22} -> {type_label(info)}")

# 引擎层面：4 对连对必须打不出去
game = GameState.new_game(seed=42, level="2")
hand = [("S", "10"), ("H", "10"), ("S", "J"), ("H", "J"),
        ("S", "Q"), ("H", "Q"), ("S", "K"), ("H", "K"), ("S", "3")]
game.hands[0] = hand

candidates = generate_candidates(hand, "2")
four_pair = [c for c in candidates if len(c) == 8 and analyze_cards(c, "2")
             and analyze_cards(c, "2")["type"] == "pair_chain"]
chains = [c for c in candidates if analyze_cards(c, "2")
          and analyze_cards(c, "2")["type"] == "pair_chain"]

print("-" * 58)
print(f"手牌含 10-J-Q-K 四对：生成的连对候选 {len(chains)} 个，全是 6 张："
      f"{all(len(c) == 6 for c in chains)}")
print(f"八张连对候选：{len(four_pair)} 个（应为 0）")

try:
    game.current_player = 0
    game.play(0, [("S", "10"), ("H", "10"), ("S", "J"), ("H", "J"),
                  ("S", "Q"), ("H", "Q"), ("S", "K"), ("H", "K")])
    print("引擎接受了 4 对连对 -> FAIL")
    ok = False
except ValueError as error:
    print(f"引擎拒绝 4 对连对 -> OK（{error}）")

print("=" * 58)
print("全部通过" if ok else "有失败项")
