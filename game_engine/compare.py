"""牌型大小比较。

规则依据（2026-11-02 项目负责人确认）：

    4 张炸弹  <  5 张同花顺  <  5 张炸弹  <  6 张炸弹  <  7 张炸弹  <  8 张炸弹
    同张数炸弹按点数比较；八张炸弹最大。
    四王炸不存在，所以「炸弹」永远只有 4~8 张同点数这一种。

超过 4 张的炸弹必然大于同花顺；4 张炸弹小于同花顺，靠 power 表实现：

    4 炸 -> 40   同花顺 -> 45   5 炸 -> 50   ...   8 炸 -> 80
"""

from game_engine.patterns import (
    TYPE_BOMB,
    TYPE_FLUSH_STRAIGHT,
    analyze_cards,
)

BOMB_MIN = 4
BOMB_MAX = 8
FLUSH_STRAIGHT_POWER = 45


def bomb_power(info):
    """炸弹类牌型的强度；普通牌型返回 -1。"""
    if info is None:
        return -1

    if info["type"] == TYPE_FLUSH_STRAIGHT:
        return FLUSH_STRAIGHT_POWER

    if info["type"] == TYPE_BOMB and BOMB_MIN <= info["count"] <= BOMB_MAX:
        return info["count"] * 10

    return -1


def compare_cards(cards_a, cards_b, level=None):
    """比较两手牌。

    返回：
         1：A 能压过 B
         0：同型同大小，或牌型无法互相压制
        -1：B 能压过 A

    无法识别的牌型会抛 ValueError，避免把非法输入静默当成「压不过」。
    """
    a = analyze_cards(cards_a, level)
    b = analyze_cards(cards_b, level)

    if a is None or b is None:
        raise ValueError("存在无法识别的牌型")

    power_a = bomb_power(a)
    power_b = bomb_power(b)

    bomb_a = power_a >= 0
    bomb_b = power_b >= 0

    # 两手都是炸弹类：先比张数等级，同等级比点数
    if bomb_a and bomb_b:
        if power_a != power_b:
            return 1 if power_a > power_b else -1
        return _compare_value(a, b)

    # 只有一手是炸弹类
    if bomb_a:
        return 1
    if bomb_b:
        return -1

    # 普通牌型必须同型、同张数才能互压
    if a["type"] != b["type"] or a["count"] != b["count"]:
        return 0

    return _compare_value(a, b)


def _compare_value(a, b):
    """按主牌牌力比较，相等返回 0。"""
    if a["main_value"] > b["main_value"]:
        return 1
    if a["main_value"] < b["main_value"]:
        return -1
    return 0


def can_beat(candidate, previous, level=None):
    """candidate 能否压过 previous。"""
    return compare_cards(candidate, previous, level) == 1
