"""状态 / 动作编码 v2 的测试。

覆盖：维度、无信息泄漏、取值范围、确定性、过牌 flag、pad / mask、
级牌 one-hot、相对座位轮转、牌池与公开信息。
"""

import copy
import math
import random

import pytest

from game_engine.cards import create_deck
from game_engine.game_state import GameState
from game_engine.ranks import BIG_JOKER, SMALL_JOKER
from training.state_encoder import (
    ACTION_DIM,
    ACTION_SEGMENTS,
    ACTION_SLICES,
    CARD_DIM,
    HAND_DIM,
    PATTERN_DIM,
    STATE_DIM,
    STATE_SEGMENTS,
    STATE_SLICES,
    encode_action,
    encode_cards,
    encode_legal_actions,
    encode_level,
    encode_state,
    pad_candidates,
)


# ---------------------------------------------------------------- 测试辅助
def make_game(hands, first_player=0, level=None):
    """构造手牌 / 长度可控的对局，并清空所有回合状态。"""
    game = GameState.new_game(seed=0)

    game.hands = [list(hand) for hand in hands]
    game.current_player = first_player
    game.leader = first_player
    game.level = level

    game.last_player = None
    game.last_play = None
    game.pass_count = 0
    game.finished_players = []
    game.game_over = False
    game.history = []

    return game


def play_randomly(game, steps, seed=0):
    """随机推进对局若干步，用于制造真实的中局状态。"""
    rng = random.Random(seed)

    for _ in range(steps):
        if game.game_over:
            break

        player = game.current_player
        moves = game.get_legal_moves(player)

        if moves and (game.last_play is None or rng.random() < 0.7):
            game.play(player, rng.choice(moves))
        elif game.last_play is not None:
            game.pass_turn(player)
        else:
            break


def assert_unit_interval(vector):
    """断言向量所有分量都是 [0, 1] 内的有限浮点数。"""
    for value in vector:
        assert isinstance(value, float)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0


# ---------------------------------------------------------------- v3 历史特征
def test_v3_history_is_empty_at_game_start():
    """开局没有任何出牌历史，历史段必须全 0。"""
    game = GameState.new_game(seed=8, level="2")
    state = encode_state(game, 0)

    assert sum(state[STATE_SLICES["history_seats"]]) == 0.0
    assert sum(state[STATE_SLICES["history_features"]]) == 0.0
    assert state[STATE_SLICES["team_progress"]][0] == 0.0


def test_v3_history_reflects_plays():
    """出牌之后，历史段必须变化（v3 的核心新增）。"""
    from training.state_encoder import STATE_SLICES

    game = GameState.new_game(seed=7, level="2")
    before = encode_state(game, 0)

    legal = game.get_legal_moves(0)
    game.play(0, legal[0])

    after = encode_state(game, 0)

    history_before = before[STATE_SLICES["history_seats"]]
    history_after = after[STATE_SLICES["history_seats"]]

    assert history_before != history_after
    # 最近一手落在最后一段座位编码里，且是「自己」
    tail = history_after[len(history_after) - 4:]
    assert sum(tail) == 1.0


def test_v3_state_ignores_other_players_card_faces():
    """只允许读别家的张数，不允许读牌面：换掉别家的牌，状态必须不变。"""
    import copy

    game = GameState.new_game(seed=9, level="2")
    state_a = encode_state(game, 0)

    clone = copy.deepcopy(game)
    clone.hands[1][0] = ("H", "A")

    state_b = encode_state(clone, 0)

    assert state_a == state_b


def test_v3_state_is_deterministic():
    """同一状态编码两次必须完全一致。"""
    game = GameState.new_game(seed=10, level="2")
    legal = game.get_legal_moves(0)
    game.play(0, legal[0])

    assert encode_state(game, 1) == encode_state(game, 1)


# ---------------------------------------------------------------- 维度
def test_dimensions_are_stable():
    """状态 / 动作维度与分段长度必须固定。

    v3（2026-11-03 起）在 v2 的 198 维之后追加了出牌历史与结构特征：
    历史座位 24 + 历史特征 24 + 双方进度 2 + 出完人数 2 + 炸弹数 2 + 手牌结构 6 = 60，
    合计 258 维。
    """
    assert STATE_DIM == 258
    assert ACTION_DIM == 65
    assert HAND_DIM == 54
    assert CARD_DIM == 54
    assert PATTERN_DIM == 9

    expected_state = {
        "hand": 54,
        "played_pool": 54,
        "hand_counts": 4,
        "last_player_seat": 4,
        "no_last_player": 1,
        "level": 14,
        "pass_count": 1,
        "is_leading": 1,
        "current_player_finished": 1,
        "last_play_cards": 54,
        "last_play_pattern": 9,
        "last_play_count": 1,
        "history_seats": 24,
        "history_features": 24,
        "team_progress": 2,
        "team_finished": 2,
        "bombs_played": 2,
        "hand_structure": 6,
    }

    assert dict(STATE_SEGMENTS) == expected_state
    assert sum(expected_state.values()) == STATE_DIM

    expected_action = {
        "cards": 54,
        "pattern": 9,
        "count": 1,
        "is_pass": 1,
    }

    assert dict(ACTION_SEGMENTS) == expected_action
    assert sum(expected_action.values()) == ACTION_DIM

    game = GameState.new_game(seed=0, level="2")

    assert len(encode_state(game)) == STATE_DIM
    assert len(encode_action(game.get_legal_moves()[0], game.level)) == ACTION_DIM


def test_default_player_is_current_player():
    game = GameState.new_game(seed=3, level="5")

    assert encode_state(game) == encode_state(game, game.current_player)


# ---------------------------------------------------------------- 牌面布局
def test_card_layout_uses_suit_and_rank():
    """54 维牌面：4 花色 × 13 点数 + 大小王。"""
    spade_3 = [0.0] * CARD_DIM
    spade_3[1] = 0.5                      # 黑桃段内的 "3"（1 张 -> 1/2）
    assert encode_cards([("S", "3")]) == spade_3

    heart_3 = [0.0] * CARD_DIM
    heart_3[13 + 1] = 0.5                 # 红桃段内的 "3"
    assert encode_cards([("H", "3")]) == heart_3

    diamond_a = [0.0] * CARD_DIM
    diamond_a[3 * 13 + 12] = 0.5          # 方块 A
    assert encode_cards([("D", "A")]) == diamond_a

    jokers = [0.0] * CARD_DIM
    jokers[52] = 0.5                      # 一张小王 -> 1 / 2
    jokers[53] = 1.0                      # 两张大王 -> 2 / 2
    assert encode_cards([SMALL_JOKER, BIG_JOKER, BIG_JOKER]) == jokers


def test_two_decks_count_to_full_slot():
    """两副牌同花色同点数最多 2 张，应编码为 1.0。"""
    vector = encode_cards([("S", "9"), ("S", "9")])

    assert vector[7] == 1.0
    assert sum(vector) == 1.0


def test_same_rank_different_suits_differ():
    """同点数不同花色必须是不同向量（v1 的核心缺陷）。"""
    assert encode_cards([("S", "3")]) != encode_cards([("H", "3")])


def test_straight_and_flush_straight_differ():
    """顺子与同花顺牌型相同点数但花色不同，编码必须不同。"""
    straight = [
        ("S", "3"), ("H", "4"), ("C", "5"), ("D", "6"), ("S", "7"),
    ]
    flush_straight = [
        ("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7"),
    ]

    normal = encode_action(straight)
    flush = encode_action(flush_straight)

    assert normal != flush
    assert normal[ACTION_SLICES["pattern"]][4] == 1.0    # straight
    assert flush[ACTION_SLICES["pattern"]][5] == 1.0     # flush_straight


# ---------------------------------------------------------------- 无泄漏
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_information_leak_from_other_hands(seed):
    """把其他三家的手牌换成别的牌后，状态向量必须逐位完全相同。"""
    game = GameState.new_game(seed=seed, level="7")
    play_randomly(game, steps=12, seed=seed)

    observer = game.current_player
    before = encode_state(game, observer)
    lengths = [len(hand) for hand in game.hands]

    clone = copy.deepcopy(game)
    deck = create_deck()
    random.Random(seed + 999).shuffle(deck)

    cursor = 0
    changed = False

    for seat in range(4):
        if seat == observer:
            continue

        replacement = deck[cursor:cursor + lengths[seat]]
        cursor += lengths[seat]

        if replacement != clone.hands[seat]:
            changed = True

        clone.hands[seat] = replacement

    assert changed, "替换用的手牌与原来完全一样，测试无效"
    assert encode_state(clone, observer) == before


def test_own_hand_is_actually_encoded():
    """反向检查：改动自己的手牌必须改变状态（防止编码器忽略手牌）。"""
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    before = encode_state(game, 0)
    game.hands[0] = [("S", "8")]

    assert encode_state(game, 0) != before


# ---------------------------------------------------------------- 公开信息
def test_hand_counts_are_relative_to_observer():
    """四家张数按 左家 / 对家 / 右家 / 自己 排列，只依赖张数。"""
    game = make_game(
        [[("S", "3")] * 3, [("H", "4")] * 5, [("C", "5")] * 7, [("D", "6")] * 9],
        first_player=0,
    )

    state = encode_state(game, 1)          # 观察者是 1
    counts = state[STATE_SLICES["hand_counts"]]

    # 左家 2 -> 7 张，对家 3 -> 9 张，右家 0 -> 3 张，自己 1 -> 5 张
    assert counts == pytest.approx([7 / 27, 9 / 27, 3 / 27, 5 / 27])
    assert all(0.0 <= value <= 1.0 for value in counts)


def test_played_pool_comes_from_public_history_only():
    """已出牌池等于 history 中所有 play 动作的牌，过牌不产生牌。"""
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    game.history = [
        {"player": 0, "action": "play", "cards": [("S", "3"), ("S", "3")]},
        {"player": 1, "action": "pass", "cards": []},
        {"player": 2, "action": "play", "cards": [SMALL_JOKER]},
    ]

    state = encode_state(game, 2)
    pool = state[STATE_SLICES["played_pool"]]

    assert pool == encode_cards([("S", "3"), ("S", "3"), SMALL_JOKER])
    assert sum(pool) == pytest.approx(1.5)


def test_played_pool_midgame_matches_history():
    """真实对局中，牌池必须与公开 history 逐位一致。"""
    game = GameState.new_game(seed=5, level="2")
    play_randomly(game, steps=10, seed=5)

    state = encode_state(game, game.current_player)
    pool = state[STATE_SLICES["played_pool"]]

    played_cards = [
        card
        for entry in game.history
        if entry["action"] == "play"
        for card in entry["cards"]
    ]

    assert pool == encode_cards(played_cards)
    assert sum(pool) == pytest.approx(len(played_cards) / 2.0)


def test_pass_count_and_leading_flags():
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    leading = encode_state(game, 0)
    assert leading[STATE_SLICES["is_leading"]][0] == 1.0
    assert leading[STATE_SLICES["pass_count"]][0] == 0.0

    game.last_play = [("S", "A")]
    game.last_player = 3
    game.pass_count = 2

    answering = encode_state(game, 0)
    assert answering[STATE_SLICES["is_leading"]][0] == 0.0
    assert answering[STATE_SLICES["pass_count"]][0] == pytest.approx(0.5)


def test_current_player_finished_flag():
    game = make_game(
        [[], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    assert encode_state(game, 0)[STATE_SLICES["current_player_finished"]][0] == 0.0

    game.finished_players = [game.current_player]

    assert encode_state(game, 0)[STATE_SLICES["current_player_finished"]][0] == 1.0


def test_last_play_encoding():
    """上一手牌：牌面 + 牌型 + 张数 都要编码。"""
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    game.last_play = [("S", "A"), ("H", "A")]
    game.last_player = 2

    state = encode_state(game, 0)

    assert state[STATE_SLICES["last_play_cards"]] == encode_cards(game.last_play)
    assert state[STATE_SLICES["last_play_pattern"]][1] == 1.0    # pair
    assert state[STATE_SLICES["last_play_count"]][0] == pytest.approx(2 / 27)


def test_no_last_play_is_all_zero_and_flagged():
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    state = encode_state(game, 0)

    assert all(value == 0.0 for value in state[STATE_SLICES["last_player_seat"]])
    assert state[STATE_SLICES["no_last_player"]][0] == 1.0
    assert all(value == 0.0 for value in state[STATE_SLICES["last_play_cards"]])
    assert all(value == 0.0 for value in state[STATE_SLICES["last_play_pattern"]])
    assert state[STATE_SLICES["last_play_count"]][0] == 0.0


# ---------------------------------------------------------------- 相对座位
def test_last_player_relative_seat_rotates():
    """上一手出牌者固定为 2；换观察者时相对座位必须正确轮转。"""
    game = make_game(
        [[("S", "3")], [("H", "4")], [("C", "5")], [("D", "6")]],
        first_player=0,
    )

    game.last_play = [("S", "A")]
    game.last_player = 2

    # 相对偏移 -> 维度下标：左家 0 / 对家 1 / 右家 2 / 自己 3
    relative_index = {
        0: 3,
        1: 0,
        2: 1,
        3: 2,
    }

    for observer in range(4):
        state = encode_state(game, observer)
        block = state[STATE_SLICES["last_player_seat"]]
        expected = relative_index[(2 - observer) % 4]

        assert block[expected] == 1.0
        assert sum(block) == 1.0
        assert state[STATE_SLICES["no_last_player"]][0] == 0.0

    # 观察者 2 自己就是上一手出牌者
    self_block = encode_state(game, 2)[STATE_SLICES["last_player_seat"]]
    assert self_block[3] == 1.0


# ---------------------------------------------------------------- 级牌
@pytest.mark.parametrize(
    "level, index",
    [
        ("2", 0),
        ("3", 1),
        ("7", 5),
        ("10", 8),
        ("A", 12),
        (None, 13),
    ],
)
def test_level_one_hot(level, index):
    game = GameState.new_game(seed=1)
    game.level = level

    state = encode_state(game, game.current_player)
    block = state[STATE_SLICES["level"]]

    assert sum(block) == 1.0
    assert block[index] == 1.0
    assert encode_level(level)[index] == 1.0


def test_invalid_level_raises():
    with pytest.raises(ValueError):
        encode_level("K2")


# ---------------------------------------------------------------- 动作编码
@pytest.mark.parametrize("empty", [None, []])
def test_pass_flag_is_unique(empty):
    """过牌只有最后 1 维为 1，和全 0 的 padding 严格不同。"""
    vector = encode_action(empty)

    assert len(vector) == ACTION_DIM
    assert vector[-1] == 1.0
    assert sum(vector) == 1.0
    assert vector != [0.0] * ACTION_DIM
    assert all(value == 0.0 for value in vector[:-1])


def test_play_action_pass_flag_is_zero():
    game = GameState.new_game(seed=2, level="9")
    moves = game.get_legal_moves()
    action = encode_action(moves[0], game.level)

    assert action[ACTION_SLICES["is_pass"]][0] == 0.0
    assert action[ACTION_SLICES["count"]][0] == pytest.approx(len(moves[0]) / 27)


def test_action_count_and_pattern():
    vector = encode_action([("S", "3")])

    assert vector[ACTION_SLICES["pattern"]][0] == 1.0          # single
    assert vector[ACTION_SLICES["count"]][0] == pytest.approx(1 / 27)


def test_encode_legal_actions():
    game = GameState.new_game(seed=11, level="2")
    moves = game.get_legal_moves()
    vectors = encode_legal_actions(moves, game.level)

    assert len(vectors) == len(moves)
    assert all(len(vector) == ACTION_DIM for vector in vectors)
    assert all(vector[ACTION_SLICES["is_pass"]][0] == 0.0 for vector in vectors)


# ---------------------------------------------------------------- pad / mask
def test_pad_candidates_with_none_padding():
    real = encode_action([("S", "3")])
    matrix, mask = pad_candidates([real, None])

    assert len(matrix) == 2
    assert len(matrix[0]) == ACTION_DIM
    assert mask == [1, 0]
    assert matrix[0] == real
    assert matrix[1] == [0.0] * ACTION_DIM


def test_pad_candidates_ragged_vectors():
    matrix, mask = pad_candidates([[1.0, 2.0], [3.0]], dim=3)

    assert matrix == [[1.0, 2.0, 0.0], [3.0, 0.0, 0.0]]
    assert mask == [1, 1]


def test_pad_candidates_infers_dim():
    matrix, mask = pad_candidates([[1.0], [2.0, 3.0, 4.0]])

    assert all(len(row) == 3 for row in matrix)
    assert matrix == [[1.0, 0.0, 0.0], [2.0, 3.0, 4.0]]
    assert mask == [1, 1]


def test_pad_candidates_empty():
    assert pad_candidates([]) == ([], [])


def test_pad_candidates_rejects_too_long_vector():
    with pytest.raises(ValueError):
        pad_candidates([[1.0, 2.0, 3.0]], dim=2)


# ---------------------------------------------------------------- 确定性 / 区间
def test_encoding_is_deterministic():
    game = GameState.new_game(seed=7, level="4")
    play_randomly(game, steps=6, seed=7)

    player = game.current_player
    first = encode_state(game, player)
    second = encode_state(game, player)
    clone = encode_state(copy.deepcopy(game), player)

    assert first == second == clone

    sample = GameState.new_game(seed=7, level="4")
    action = sample.get_legal_moves()[0]
    assert encode_action(action, sample.level) == encode_action(action, sample.level)


def test_all_values_are_normalized():
    """整局推进过程中，状态与所有候选动作都必须落在 [0, 1]。"""
    for seed in range(2):
        game = GameState.new_game(seed=seed, level="7")
        rng = random.Random(seed + 50)

        for _ in range(40):
            if game.game_over:
                break

            player = game.current_player
            state = encode_state(game, player)
            assert_unit_interval(state)

            moves = game.get_legal_moves(player)
            vectors = encode_legal_actions(moves, game.level)

            for vector in vectors:
                assert_unit_interval(vector)

            if game.last_play is not None:
                assert_unit_interval(encode_action(None, game.level))

            if moves and (game.last_play is None or rng.random() < 0.7):
                game.play(player, rng.choice(moves))
            elif game.last_play is not None:
                game.pass_turn(player)
            else:
                break
