"""牌的紧凑序列化，供数据集落盘使用。

内存里的牌是 ("S", "3") 这样的元组，大小王是 "SJ" / "BJ"。

落盘统一写成 "S:3" / "H:10" / "SJ" / "BJ"。
**必须带分隔符**：如果写成 "S3" 这种拼接形式，("S", "J") 会变成 "SJ"，
和小王撞车——重放时黑桃 J 会被解析成小王，手牌全部错位。
"""

from game_engine.ranks import BIG_JOKER, SMALL_JOKER

SEPARATOR = ":"

JOKERS = (SMALL_JOKER, BIG_JOKER)


def card_to_text(card):
    """把一张牌变成短字符串。"""
    if isinstance(card, str):
        if card not in JOKERS:
            raise ValueError(f"无法识别的王：{card}")

        return card

    suit, rank = card
    return f"{suit}{SEPARATOR}{rank}"


def text_to_card(text):
    """把短字符串还原成牌。"""
    if SEPARATOR in text:
        suit, rank = text.split(SEPARATOR, 1)

        if not suit or not rank:
            raise ValueError(f"无法解析的牌：{text}")

        return (suit, rank)

    if text in JOKERS:
        return text

    raise ValueError(f"无法解析的牌：{text}（普通牌必须写成 S:3 这种带冒号的形式）")


def cards_to_text(cards):
    if cards is None:
        return None

    return [card_to_text(card) for card in cards]


def text_to_cards(texts):
    if texts is None:
        return None

    return [text_to_card(text) for text in texts]


def hand_to_text(hand):
    return [card_to_text(card) for card in hand]


def text_to_hand(texts):
    return [text_to_card(text) for text in texts]
