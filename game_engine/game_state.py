
import random
from collections import Counter

from game_engine.cards import create_deck
from game_engine.legal_moves import legal_moves


class GameState:
    """
    四人掼蛋基础对局状态。

    玩家编号：
        0 和 2：A队
        1 和 3：B队

    出牌方向：0 -> 1 -> 2 -> 3 -> 0
    """

    def __init__(self, hands, first_player=0, level=None):
        if len(hands) != 4:
            raise ValueError("必须有四名玩家")

        if any(len(hand) != 27 for hand in hands):
            raise ValueError("每名玩家初始手牌必须为27张")

        self.hands = [list(hand) for hand in hands]

        self.current_player = first_player
        self.leader = first_player

        self.last_player = None
        self.last_play = None

        self.pass_count = 0

        self.finished_players = []
        self.game_over = False

        # 本局打几（"2".."A"）。None 表示无级牌模式，D1.5 起启用。
        self.level = level

        self.history = []

    @classmethod
    def new_game(cls, seed=None, first_player=0, level=None):
        """创建一局随机发牌的游戏。"""

        deck = create_deck()

        if len(deck) != 108:
            raise ValueError("牌堆必须有108张牌")

        rng = random.Random(seed)
        rng.shuffle(deck)

        hands = [
            deck[i * 27:(i + 1) * 27]
            for i in range(4)
        ]

        return cls(hands, first_player, level)

    @staticmethod
    def teammate(player):
        """返回队友编号。"""
        return (player + 2) % 4

    def next_player(self, player):
        """寻找下一个尚未出完牌的玩家。"""

        for step in range(1, 5):
            candidate = (player + step) % 4

            if candidate not in self.finished_players:
                return candidate

        return None

    def get_legal_moves(self, player=None):
        """获取指定玩家当前可以出的牌。"""

        if self.game_over:
            return []

        if player is None:
            player = self.current_player

        if player != self.current_player:
            return []

        if player in self.finished_players:
            return []

        previous = self.last_play

        # 2026-11-03 负责人确认：**可以压队友的牌**。
        # 之前这里是「队友出牌时返回空列表（只能过牌）」，已按确认表移除。
        # 「不压队友」现在只是策略偏好（见 players/heuristic.py），不是规则限制。
        return legal_moves(self.hands[player], previous, self.level)

    def play(self, player, cards):
        """玩家出牌。"""

        if self.game_over:
            raise ValueError("游戏已经结束")

        if player != self.current_player:
            raise ValueError("现在还没有轮到这名玩家")

        if player in self.finished_players:
            raise ValueError("这名玩家已经出完牌")

        if not cards:
            raise ValueError("出牌不能为空")

        hand = self.hands[player]

        # 检查所选牌是否确实在手中
        if not Counter(cards) <= Counter(hand):
            raise ValueError("所选牌不属于当前玩家")

        # 检查合法出牌
        candidates = self.get_legal_moves(player)

        if not any(
            Counter(move) == Counter(cards)
            for move in candidates
        ):
            raise ValueError("这手牌不符合当前出牌规则")

        # 从手牌中移除打出的牌
        remaining = list(hand)

        for card in cards:
            remaining.remove(card)

        self.hands[player] = remaining

        self.last_play = list(cards)
        self.last_player = player
        self.leader = player
        self.pass_count = 0

        self.history.append({
            "player": player,
            "action": "play",
            "cards": list(cards),
        })

        # 判断玩家是否出完
        if len(self.hands[player]) == 0:
            self.finished_players.append(player)

            # 三人出完，最后一人为第四名
            if len(self.finished_players) == 3:
                for remaining_player in range(4):
                    if remaining_player not in self.finished_players:
                        self.finished_players.append(remaining_player)
                        break

                self.game_over = True

        if not self.game_over:
            self.current_player = self.next_player(player)

        return True

    def pass_turn(self, player):
        """玩家选择过牌。"""

        if self.game_over:
            raise ValueError("游戏已经结束")

        if player != self.current_player:
            raise ValueError("现在还没有轮到这名玩家")

        if self.last_play is None:
            raise ValueError("领出阶段不能过牌")

        if self.last_player == player:
            raise ValueError("不能跳过自己的领出")

        self.pass_count += 1

        self.history.append({
            "player": player,
            "action": "pass",
            "cards": [],
        })

        # 根据当前仍在游戏中的玩家动态计算过牌人数
        active_count = 4 - len(self.finished_players)

        # 如果上一手出牌者已经出完，
        # 所有剩余玩家都需要过牌；
        # 否则不需要上一手出牌者自己过牌。
        required_passes = active_count

        if self.last_player not in self.finished_players:
            required_passes -= 1

        if self.pass_count >= required_passes:

            self.last_play = None
            self.last_player = None
            self.pass_count = 0

            # 暂时沿用当前领出者作为下一轮领出者。
            # 领出者已经出完牌时的接续规则，
            # 留待根据完整纸质规则进一步确认。
            if self.leader in self.finished_players:
                self.current_player = self.next_player(self.leader)
            else:
                self.current_player = self.leader

        else:
            self.current_player = self.next_player(player)

        return True

    def show_status(self):
        """显示当前对局状态。"""

        print("\n========== 当前对局 ==========")

        for player in range(4):
            team = "A队" if player in (0, 2) else "B队"

            if player in self.finished_players:
                status = "已出完"
            else:
                status = f"剩余 {len(self.hands[player])} 张"

            print(
                f"玩家 {player} | {team} | {status}"
            )

        print("------------------------------")

        if self.last_play is None:
            print("当前桌面：无人领出")
        else:
            print(f"上一手出牌：玩家 {self.last_player}")
            print(f"桌面牌：{self.last_play}")

        print(f"当前行动玩家：{self.current_player}")

        if self.game_over:
            print(f"游戏结束！名次：{self.finished_players}")

        print("==============================\n")


if __name__ == "__main__":

    game = GameState.new_game(seed=42)

    print("GuanDan AI Lab - 对局引擎测试")

    game.show_status()

    print("四名玩家手牌数量：")

    for player in range(4):
        print(f"玩家 {player}：{len(game.hands[player])} 张")

    print("\n当前玩家可以出的牌：")

    moves = game.get_legal_moves()

    print(f"合法出牌数量：{len(moves)}")

    for move in moves[:10]:
        print(move)

    print("\n测试完成。")
