
import random
from collections import Counter

SUITS = ("S", "H", "C", "D")

RANKS = (
    "3", "4", "5", "6", "7",
    "8", "9", "10", "J", "Q",
    "K", "A", "2"
)

SMALL_JOKER = "SJ"
BIG_JOKER = "BJ"


def create_deck():
    """创建两副扑克牌，共108张。"""
    deck = []

    for _ in range(2):
        for suit in SUITS:
            for rank in RANKS:
                deck.append((suit, rank))

        deck.append(SMALL_JOKER)
        deck.append(BIG_JOKER)

    assert len(deck) == 108
    return deck


def shuffle_deck(deck, seed=None):
    """洗牌。"""
    cards = deck.copy()
    rng = random.Random(seed)
    rng.shuffle(cards)
    return cards


def deal_cards(seed=None):
    """四人发牌，每人27张。"""
    deck = shuffle_deck(create_deck(), seed)

    hands = [
        deck[i * 27:(i + 1) * 27]
        for i in range(4)
    ]

    assert all(len(hand) == 27 for hand in hands)

    return hands


def count_cards(hand):
    """统计手牌点数。"""
    counts = Counter()

    for card in hand:
        if card in (SMALL_JOKER, BIG_JOKER):
            counts[card] += 1
        else:
            counts[card[1]] += 1

    return counts
