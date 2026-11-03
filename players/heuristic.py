import random
from collections import Counter

from game_engine.patterns import (
    TYPE_BOMB,
    TYPE_FLUSH_STRAIGHT,
    analyze_cards,
)
from game_engine.ranks import (
    natural_value,
    rank_of,
    rank_value as card_rank_value,
)


def rank_value(card):
    """一张牌的基础牌力（2 最小，A 最大，王在最后）。

    注意：这是不含级牌上浮的旧接口；内部评估统一走 card_rank_value(rank, level)。
    """
    return natural_value(rank_of(card))


def hand_cost(hand, level=None):
    """评估剩余手牌结构，分数越低越好。

    level 用于级牌牌力上浮：级牌在非连续牌型里按 15 计算。
    """

    counts = Counter(rank_of(card) for card in hand)
    cost = 0.0

    for rank, count in counts.items():
        value = card_rank_value(rank, level)

        if count == 1:
            cost += 1.30
            cost -= value * 0.015
        elif count == 2:
            cost += 0.62
        elif count == 3:
            cost += 0.28
        elif count >= 4:
            cost += 0.12

    return cost


def move_cost(move, level=None):
    """估算出牌消耗的战略价值。"""

    info = analyze_cards(move, level)

    if info is None:
        return 1000.0

    if info["type"] == TYPE_BOMB:
        return 2.8

    if info["type"] == TYPE_FLUSH_STRAIGHT:
        return 2.0

    return 0.0


def evaluate_move(hand, move, level=None):
    """评估出牌后剩余手牌的质量。"""

    remaining = list(hand)

    for card in move:
        try:
            remaining.remove(card)
        except ValueError:
            return 10000.0

    return (
        hand_cost(remaining, level)
        + move_cost(move, level)
        - len(move) * 0.025
    )


def choose_move(
    hand,
    legal_moves,
    rng=None,
    game_state=None,
    player=None,
    level=None
):
    """
    选择策略出牌。

    如果有 game_state 和 player，
    会额外考虑队友、对手剩余手牌和是否值得过牌。

    level 为本局级牌（"2".."A"）。未显式传入时从 game_state.level 读取；
    它决定级牌牌力与逢人配的判定。

    返回：
        一手牌：选择出牌
        None：选择过牌
    """

    if rng is None:
        rng = random.Random()

    # 级牌影响牌型识别（级牌上浮、逢人配），能拿到就一定要传下去
    if level is None and game_state is not None:
        level = getattr(game_state, "level", None)

    if not legal_moves:
        return None

    # 先计算所有候选牌的基础分数
    scored_moves = []

    for move in legal_moves:
        score = evaluate_move(hand, move, level)
        scored_moves.append((score, move))

    best_score = min(score for score, move in scored_moves)

    candidates = [
        move
        for score, move in scored_moves
        if score <= best_score + 0.08
    ]

    selected = rng.choice(candidates)

    # 没有对局信息时，沿用原来的策略
    if game_state is None or player is None:
        return selected

    last_player = game_state.last_player

    if last_player is None:
        return selected

    # 队友已经控制桌面，不主动争夺牌权
    if game_state.teammate(player) == last_player:
        return None

    # 统计仍在游戏中的对手剩余手牌
    opponents = [
        p for p in range(4)
        if p != player
        and p != game_state.teammate(player)
        and p not in game_state.finished_players
    ]

    if not opponents:
        return selected

    min_opponent_cards = min(
        len(game_state.hands[p])
        for p in opponents
    )

    selected_info = analyze_cards(selected, level)

    # 对手只剩少量手牌时，提高争夺牌权的意愿
    urgent = min_opponent_cards <= 3

    # 普通情况下，避免为了一般牌型付出太大代价
    selected_cost = move_cost(selected, level)

    if not urgent:
        if selected_cost >= 2.0:
            return None

        # 如果出牌会明显破坏手牌结构，可以考虑过牌
        if evaluate_move(hand, selected, level) > hand_cost(hand, level) + 0.5:
            return None

    # 对手即将出完牌时，优先争夺控制权
    if urgent:
        if selected_info is not None:
            return selected

    return selected


if __name__ == "__main__":

    print("GuanDan AI Lab - 升级版启发式策略测试")
    print("=" * 55)

    hand = [
        ("S", "3"),
        ("H", "3"),
        ("D", "3"),
        ("C", "4"),
        ("H", "4"),
        ("D", "5"),
        ("S", "6"),
        ("C", "7"),
    ]

    candidates = [
        [("S", "3")],
        [("S", "3"), ("H", "3")],
        [("S", "3"), ("H", "3"), ("D", "3")],
        [("C", "4"), ("H", "4")],
        [("D", "5")],
    ]

    selected = choose_move(
        hand,
        candidates,
        rng=random.Random(42)
    )

    print("当前手牌：", hand)
    print("\n候选出牌及评分：")

    for move in candidates:
        print(
            move,
            "评分：",
            round(evaluate_move(hand, move), 3)
        )

    print("\n策略选择：", selected)
    print("\n测试完成。")
