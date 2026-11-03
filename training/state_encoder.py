"""状态与动作编码 v3。

本模块把一局掼蛋的**公开信息**与**自己的手牌**编码成定长浮点向量，
供策略网络 / 数据集使用。

版本历史：

* **v1**（原型）：把牌面压成点数计数，丢了花色，顺子与同花顺无法区分。
* **v2**（198 维）：① 保留花色（4 花色 × 13 点数 + 双王 = 54 维）；
  ② 绝不读别家手牌的具体牌面，只读张数；③ 加入已出牌池、级牌、pass_count；
  ④ 座位改成相对位置（左家 / 对家 / 右家 / 自己）；⑤ 过牌用独立 flag。
* **v3**（258 维，2026-11-03）：在 v2 基础上补上"**时间维度**"——
  原来的状态只有"上一手"，网络看不到之前发生了什么。v3 追加：
  * 最近 6 手的**出牌序列**（每手：出牌者相对座位 4 维 + 是否过牌 / 牌型 / 张数 / 主牌力 4 维）；
  * 双方进度（各队已出多少张、各队已出完几人、各队已用几个炸弹）；
  * 自己手牌的**结构纹理**（王数、逢人配数、成对点数、成三点数、炸弹组数、最大炸弹张数）。

牌面编码共 54 维，顺序固定为::

    黑桃 2..A (13) | 红桃 2..A (13) | 梅花 2..A (13) | 方块 2..A (13)
    | 小王 (1) | 大王 (1)

每个槽位存该「花色 + 点数」的计数（两副牌同花色同点数最多 2 张），
再除以 2 归一化到 [0, 1]；大小王同样除以 2。

相对座位顺序固定为 ``左家 / 对家 / 右家 / 自己``，即相对偏移
``+1 / +2 / +3 / 0``（出牌顺序 0 -> 1 -> 2 -> 3，对家 = +2）。
状态一律以 ``player``（观测者，通常就是当前行动者）为基准。

状态向量（258 维）分段::

    手牌 54 | 已出牌池 54 | 四家剩余张数 4
    | 上一手玩家相对座位 4 | 无上一手 1
    | 级牌 14 | pass_count 1 | 是否领出 1 | 当前玩家是否出完 1
    | 上一手牌 54 | 上一手牌型 9 | 上一手张数 1
    | 历史座位 24 | 历史特征 24 | 双方进度 2 | 出完人数 2 | 炸弹数 2 | 手牌结构 6

动作向量（65 维）分段::

    牌 54 | 牌型 9 | 张数 1 | 是否过牌 1

所有取值都在 [0, 1] 内，且同一输入多次调用结果完全一致（纯函数）。

兼容性说明：``encode_cards`` 也接受 ``"3"`` 这样的**点数缩写**（旧测试
常用这种写法），此时统一记到黑桃槽位；正式对局必须使用
``("S", "3")`` 元组或 ``"SJ"`` / ``"BJ"``。

⚠️ 训练好的 checkpoint 会记录 ``encoder_version``；用 v2 模型配 v3 编码器
会在加载时报出可读的错误，而不是形状不匹配的堆栈。
"""

from game_engine.patterns import PATTERN_TYPES as _PATTERN_TYPES
from game_engine.patterns import analyze_cards
from game_engine.ranks import (
    BIG_JOKER,
    NORMAL_RANKS,
    SMALL_JOKER,
    SUITS,
    rank_of,
    suit_of,
)

# ---------------------------------------------------------------- 牌面布局
# 13 个普通点数，按自然牌力升序（2 最小）
LEVEL_RANKS = tuple(NORMAL_RANKS)

RANK_INDEX = {
    rank: index
    for index, rank in enumerate(LEVEL_RANKS)
}

SUIT_INDEX = {
    suit: index
    for index, suit in enumerate(SUITS)
}

# 每个花色 13 个槽位；两副牌同一槽位最多 2 张
RANKS_PER_SUIT = len(LEVEL_RANKS)
JOKER_OFFSET = len(SUITS) * RANKS_PER_SUIT          # 52
SMALL_JOKER_INDEX = JOKER_OFFSET                    # 52
BIG_JOKER_INDEX = JOKER_OFFSET + 1                  # 53
CARD_DIM = JOKER_OFFSET + 2                         # 54

# 旧代码里可能用到的名字；v2 的牌面向量就是 54 维
HAND_DIM = CARD_DIM
POOL_DIM = CARD_DIM

# ---------------------------------------------------------------- 牌型布局
# 固定 9 种牌型，顺序与 game_engine.patterns.PATTERN_TYPES 一致
PATTERN_TYPES = tuple(_PATTERN_TYPES)
PATTERN_INDEX = {
    pattern: index
    for index, pattern in enumerate(PATTERN_TYPES)
}
PATTERN_DIM = len(PATTERN_TYPES)                    # 9

# ---------------------------------------------------------------- 其他布局
SEAT_DIM = 4            # 左家 / 对家 / 右家 / 自己
LEVEL_DIM = len(LEVEL_RANKS) + 1                    # 13 个点数 + 「无级牌」
LAST_PLAY_DIM = CARD_DIM + PATTERN_DIM + 1          # 54 + 9 + 1
MAX_HAND = 27           # 每人初始 27 张，用于归一化

# 相对座位顺序：左家(+1) / 对家(+2) / 右家(+3) / 自己(+0)
RELATIVE_ORDER = (1, 2, 3, 0)
RELATIVE_INDEX = {
    offset: index
    for index, offset in enumerate(RELATIVE_ORDER)
}

# ---------------------------------------------------------------- v3 历史特征
# 编码器版本：v2 = 198 维（只有上一手）；v3 = 258 维（含最近 6 手序列 + 结构特征）
ENCODER_VERSION = 3
ENCODER_VERSION_V2 = 2

# 最近多少手进入状态向量
HISTORY_LEN = 6

# 每手 4 个特征：是否过牌、牌型序号、张数、主牌力
HISTORY_FEATURE_DIM = 4

MAX_PLAY_CARDS = 8          # 炸弹最多 8 张（两副牌同点最多 8）
MAX_MAIN_VALUE = 17         # 大王

# 手牌结构 6 维：王数、逢人配数、成对点数、成三点数、炸弹组数、最大炸弹张数
HAND_STRUCTURE_DIM = 6
MAX_PAIR_CLUSTERS = 6
MAX_TRIPLE_CLUSTERS = 6
MAX_BOMB_GROUPS = 3

# 状态向量分段表：(段名, 长度)，顺序即拼接顺序
STATE_SEGMENTS = (
    ("hand", HAND_DIM),                              # 54
    ("played_pool", POOL_DIM),                       # 54
    ("hand_counts", 4),                              # 4
    ("last_player_seat", SEAT_DIM),                  # 4
    ("no_last_player", 1),                           # 1
    ("level", LEVEL_DIM),                            # 14
    ("pass_count", 1),                               # 1
    ("is_leading", 1),                               # 1
    ("current_player_finished", 1),                  # 1
    ("last_play_cards", CARD_DIM),                   # 54
    ("last_play_pattern", PATTERN_DIM),              # 9
    ("last_play_count", 1),                          # 1
    # ---- v3 新增：出牌历史序列与结构特征 ----
    ("history_seats", HISTORY_LEN * SEAT_DIM),       # 24
    ("history_features", HISTORY_LEN * HISTORY_FEATURE_DIM),  # 24
    ("team_progress", 2),                            # 2
    ("team_finished", 2),                            # 2
    ("bombs_played", 2),                             # 2
    ("hand_structure", HAND_STRUCTURE_DIM),          # 6
)

# 动作向量分段表
ACTION_SEGMENTS = (
    ("cards", CARD_DIM),                             # 54
    ("pattern", PATTERN_DIM),                        # 9
    ("count", 1),                                    # 1
    ("is_pass", 1),                                  # 1
)


def _build_slices(segments):
    """把分段表换算成 {段名: slice}，便于外部按段取用。"""
    slices = {}
    start = 0

    for name, size in segments:
        slices[name] = slice(start, start + size)
        start += size

    return slices


STATE_SLICES = _build_slices(STATE_SEGMENTS)
ACTION_SLICES = _build_slices(ACTION_SEGMENTS)

STATE_DIM = sum(size for _, size in STATE_SEGMENTS)     # 198
ACTION_DIM = sum(size for _, size in ACTION_SEGMENTS)   # 65


# ---------------------------------------------------------------- 基础工具
def card_rank(card):
    """提取一张牌的点数，无法识别时报错。"""
    rank = rank_of(card)

    if rank in (SMALL_JOKER, BIG_JOKER):
        return rank

    if rank not in RANK_INDEX:
        raise ValueError(f"无法识别的牌点：{rank!r}")

    return rank


def card_index(card):
    """把一张牌映射到 54 维牌面向量的下标。"""
    rank = card_rank(card)

    if rank == SMALL_JOKER:
        return SMALL_JOKER_INDEX

    if rank == BIG_JOKER:
        return BIG_JOKER_INDEX

    suit = suit_of(card)

    if suit is None:
        # 兼容旧测试的 "3" 写法；正式对局不应出现无花色的普通牌
        suit = SUITS[0]

    if suit not in SUIT_INDEX:
        raise ValueError(f"无法识别的花色：{suit!r}")

    return SUIT_INDEX[suit] * RANKS_PER_SUIT + RANK_INDEX[rank]


def _count_cards(cards):
    """统计一组牌在 54 个槽位上的原始张数（整数）。"""
    counts = [0] * CARD_DIM

    for card in cards:
        counts[card_index(card)] += 1

    return counts


def _normalize_card_counts(counts):
    """牌面计数除以 2 并截断到 [0, 1]（防御异常数据）。"""
    return [
        min(max(count, 0), 2) / 2.0
        for count in counts
    ]


def encode_cards(cards):
    """将一组牌编码成 54 维、归一化后的计数向量。

    槽位顺序：4 花色 × 13 点数 + 小王 + 大王。
    """
    return _normalize_card_counts(_count_cards(cards))


def encode_played_pool(game):
    """从公开的 ``game.history`` 累计已出牌池（54 维）。

    只统计 ``action == "play"`` 的记录，过牌不产生牌。
    """
    counts = [0] * CARD_DIM

    for entry in getattr(game, "history", None) or []:
        if entry.get("action") != "play":
            continue

        for card in entry.get("cards") or []:
            counts[card_index(card)] += 1

    return _normalize_card_counts(counts)


def encode_hand_counts(game, player):
    """四家剩余手牌数（4 维，除以 27），按相对座位顺序排列。

    顺序为 左家 / 对家 / 右家 / 自己。只使用**张数**，不使用牌面。
    """
    order = [
        (player + offset) % 4
        for offset in RELATIVE_ORDER
    ]

    return [
        min(max(len(game.hands[seat]), 0), MAX_HAND) / MAX_HAND
        for seat in order
    ]


def encode_relative_seat(seat, player):
    """把一个绝对座位编码成相对 ``player`` 的 4 维 one-hot。

    顺序：左家 / 对家 / 右家 / 自己。
    """
    offset = (seat - player) % 4
    index = RELATIVE_INDEX[offset]

    result = [0.0] * SEAT_DIM
    result[index] = 1.0
    return result


def encode_last_player(game, player):
    """上一手出牌者的相对座位（4 维）+ 「无上一手」标记（1 维）。

    没有上一手牌时 4 维全 0、标记为 1；有上一手时标记为 0。
    """
    no_last_player = (
        getattr(game, "last_play", None) is None
        or getattr(game, "last_player", None) is None
    )

    if no_last_player:
        return [0.0] * SEAT_DIM + [1.0]

    return encode_relative_seat(game.last_player, player) + [0.0]


def encode_level(level):
    """级牌 one-hot（14 维）：13 个普通点数 + 「无级牌」。"""
    result = [0.0] * LEVEL_DIM

    if level is None:
        result[LEVEL_DIM - 1] = 1.0
        return result

    if level not in RANK_INDEX:
        raise ValueError(f"无法识别的级牌：{level!r}")

    result[RANK_INDEX[level]] = 1.0
    return result


def encode_pattern(cards, level=None):
    """将牌型编码成 9 维 one-hot。

    空牌或无法识别的牌型返回全 0（过牌另有独立 flag，不靠这个区分）。
    """
    result = [0.0] * PATTERN_DIM

    if not cards:
        return result

    info = analyze_cards(cards, level)

    if info is None:
        return result

    pattern_type = info.get("type")

    if pattern_type in PATTERN_INDEX:
        result[PATTERN_INDEX[pattern_type]] = 1.0

    return result


def encode_turn_state(game, player):
    """轮次状态（3 维）：pass_count、是否领出、当前玩家是否已出完。"""
    pass_count = min(max(getattr(game, "pass_count", 0), 0), 4) / 4.0
    is_leading = 1.0 if getattr(game, "last_play", None) is None else 0.0

    current_player = getattr(game, "current_player", None)
    current_finished = (
        1.0
        if current_player in (getattr(game, "finished_players", None) or [])
        else 0.0
    )

    return [pass_count, is_leading, current_finished]


def _encode_count(count):
    """张数归一化：除以 27 并截断到 [0, 1]。"""
    return min(max(count, 0), MAX_HAND) / MAX_HAND


# ---------------------------------------------------------------- v3 历史特征
def _encode_play_features(entry, level):
    """一手牌（或一次过牌）的 4 个特征：是否过牌、牌型、张数、主牌力。"""
    if entry.get("action") != "play":
        return [1.0, 0.0, 0.0, 0.0]

    cards = entry.get("cards") or []

    if not cards:
        return [1.0, 0.0, 0.0, 0.0]

    info = analyze_cards(cards, level)
    pattern = (
        PATTERN_INDEX.get(info.get("type"), 0) / max(len(PATTERN_TYPES) - 1, 1)
        if info
        else 0.0
    )
    count = min(len(cards), MAX_PLAY_CARDS) / MAX_PLAY_CARDS
    main = (
        min(info.get("main_value", 0), MAX_MAIN_VALUE) / MAX_MAIN_VALUE
        if info
        else 0.0
    )

    return [0.0, pattern, count, main]


def encode_history(game, player):
    """最近 ``HISTORY_LEN`` 手：座位 one-hot（24）+ 特征（24）。

    最早的在前、最新的在后；不足时在**前面**补零，
    这样"最近一手"永远落在固定位置，网络能稳定读到最后一位。
    """
    history = list(getattr(game, "history", None) or [])[-HISTORY_LEN:]
    level = getattr(game, "level", None)

    seats = []
    features = []

    for _ in range(HISTORY_LEN - len(history)):
        seats.extend([0.0] * SEAT_DIM)
        features.extend([0.0] * HISTORY_FEATURE_DIM)

    for entry in history:
        actor = entry.get("player")

        if actor in (0, 1, 2, 3):
            seats.extend(encode_relative_seat(actor, player))
        else:
            seats.extend([0.0] * SEAT_DIM)

        features.extend(_encode_play_features(entry, level))

    return seats + features


def encode_team_context(game, player):
    """双方进度 6 维：已出牌数（2）、出完人数（2）、已用炸弹数（2）。"""
    level = getattr(game, "level", None)
    my_team = player % 2

    my_cards = 0
    enemy_cards = 0
    my_bombs = 0
    enemy_bombs = 0

    for entry in getattr(game, "history", None) or []:
        if entry.get("action") != "play":
            continue

        cards = entry.get("cards") or []
        is_mine = (entry.get("player", 0) % 2) == my_team

        if is_mine:
            my_cards += len(cards)
        else:
            enemy_cards += len(cards)

        info = analyze_cards(cards, level) if cards else None

        if info and info.get("type") in ("bomb", "flush_straight"):
            if is_mine:
                my_bombs += 1
            else:
                enemy_bombs += 1

    finished = getattr(game, "finished_players", None) or []
    my_finished = sum(1 for seat in finished if seat % 2 == my_team)
    enemy_finished = len(finished) - my_finished

    return [
        min(my_cards, 54) / 54,
        min(enemy_cards, 54) / 54,
        my_finished / 2,
        enemy_finished / 2,
        min(my_bombs, 4) / 4,
        min(enemy_bombs, 4) / 4,
    ]


def encode_hand_structure(game, player):
    """手牌结构 6 维：王、逢人配、成对点数、成三点数、炸弹组数、最大炸弹张数。

    这些是"牌力纹理"特征，帮助网络判断手里是"散牌等顺子"还是"炸弹蓄势"。
    """
    from collections import Counter

    hand = game.hands[player]
    level = getattr(game, "level", None)

    jokers = 0
    wildcards = 0
    rank_counts = Counter()

    for card in hand:
        rank = card_rank(card)

        if rank in (SMALL_JOKER, BIG_JOKER):
            jokers += 1
            continue

        if level is not None and suit_of(card) == SUITS[1] and rank == level:
            wildcards += 1

        rank_counts[rank] += 1

    pairs = sum(1 for count in rank_counts.values() if count >= 2)
    triples = sum(1 for count in rank_counts.values() if count >= 3)
    bombs = sum(1 for count in rank_counts.values() if count >= 4)
    max_bomb = max(rank_counts.values(), default=0)

    return [
        min(jokers, 2) / 2,
        min(wildcards, 2) / 2,
        min(pairs, MAX_PAIR_CLUSTERS) / MAX_PAIR_CLUSTERS,
        min(triples, MAX_TRIPLE_CLUSTERS) / MAX_TRIPLE_CLUSTERS,
        min(bombs, MAX_BOMB_GROUPS) / MAX_BOMB_GROUPS,
        min(max_bomb, MAX_PLAY_CARDS) / MAX_PLAY_CARDS,
    ]


# ---------------------------------------------------------------- 状态编码
def encode_state(game, player=None):
    """编码当前牌局状态，返回 198 维浮点列表。

    ``player`` 为观测者（默认当前行动者）。只读取 ``game.hands[player]``
    与公开信息；其他三家的具体牌面绝不参与计算。

    注意：v2 假定观测者就是行动者（数据采集时恒成立），因此没有单独
    编码「当前行动者的相对座位」；若需要离线编码旁观视角，可在此追加。
    """
    if player is None:
        player = game.current_player

    if player not in (0, 1, 2, 3):
        raise ValueError("玩家编号必须是0、1、2或3")

    level = getattr(game, "level", None)
    last_play = getattr(game, "last_play", None) or []

    result = (
        encode_cards(game.hands[player])
        + encode_played_pool(game)
        + encode_hand_counts(game, player)
        + encode_last_player(game, player)
        + encode_level(level)
        + encode_turn_state(game, player)
        + encode_cards(last_play)
        + encode_pattern(last_play, level)
        + [_encode_count(len(last_play))]
        # ---- v3 ----
        + encode_history(game, player)
        + encode_team_context(game, player)
        + encode_hand_structure(game, player)
    )

    assert len(result) == STATE_DIM
    return result


# ---------------------------------------------------------------- 动作编码
def encode_action(action, level=None):
    """编码一个候选动作，返回 65 维浮点列表。

    ``action`` 为牌列表；``None`` 或空列表表示过牌，此时最后 1 维为 1，
    其余全 0。过牌向量因此与 padding 的全 0 向量严格可区分。
    """
    if not action:
        return (
            [0.0] * CARD_DIM
            + [0.0] * PATTERN_DIM
            + [0.0]
            + [1.0]
        )

    cards = list(action)

    return (
        encode_cards(cards)
        + encode_pattern(cards, level)
        + [_encode_count(len(cards))]
        + [0.0]
    )


def encode_legal_actions(legal_moves, level=None):
    """批量编码当前所有合法动作。"""
    return [
        encode_action(move, level)
        for move in legal_moves
    ]


def pad_candidates(vectors, dim=None):
    """把变长候选向量补齐成矩阵，并返回真实候选 mask。

    参数：
        vectors: 候选向量序列；元素为 ``None`` 时视为占位 padding。
        dim: 目标维度；``None`` 时取所有真实向量的最大长度，
            没有真实向量时取 ``ACTION_DIM``。

    返回：
        (padded_matrix, mask)
        mask 为 1 表示真实候选，0 表示 padding（对应行全 0）。
    """
    items = list(vectors)

    if dim is None:
        lengths = [
            len(item)
            for item in items
            if item is not None
        ]
        dim = max(lengths) if lengths else ACTION_DIM

    dim = int(dim)

    if dim <= 0:
        raise ValueError("dim 必须是正整数")

    matrix = []
    mask = []

    for item in items:
        if item is None:
            matrix.append([0.0] * dim)
            mask.append(0)
            continue

        row = list(item)

        if len(row) > dim:
            raise ValueError(
                f"候选向量长度 {len(row)} 超过目标维度 {dim}"
            )

        matrix.append(row + [0.0] * (dim - len(row)))
        mask.append(1)

    return matrix, mask


if __name__ == "__main__":
    from game_engine.game_state import GameState

    game = GameState.new_game(seed=42, level="2")
    state = encode_state(game)
    moves = game.get_legal_moves()
    actions = encode_legal_actions(moves, game.level)

    print("GuanDan AI Lab - 状态 / 动作编码 v2 自检")
    print("=" * 56)
    print(f"STATE_DIM = {STATE_DIM}")
    print(f"ACTION_DIM = {ACTION_DIM}")
    print(f"状态向量长度 = {len(state)}")
    print(f"合法动作数 = {len(moves)}")

    if actions:
        print(f"单个动作向量长度 = {len(actions[0])}")

    matrix, mask = pad_candidates(actions)
    print(f"补齐矩阵形状 = {len(matrix)} x {len(matrix[0]) if matrix else 0}")
    print(f"mask 求和 = {sum(mask)}")
    print("自检完成。")
