
import json
from pathlib import Path
from datetime import datetime


def serialize_cards(cards):
    if cards is None:
        return None

    result = []

    for card in cards:
        if isinstance(card, tuple):
            result.append(list(card))
        else:
            result.append(card)

    return result


class GameLogger:

    def __init__(self, seed=None, output_dir=None, prefix="game"):
        output_dir = (
            Path(output_dir)
            if output_dir is not None
            else Path(__file__).resolve().parent
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}_{seed}.jsonl"

        self.file_path = output_dir / filename
        self.file = self.file_path.open(
            "w",
            encoding="utf-8"
        )

        self.turn_count = 0
        self.seed = seed
        self.closed = False

        self.write({
            "event": "game_start",
            "seed": seed,
            "time": datetime.now().isoformat()
        })

    def write(self, data):
        self.file.write(
            json.dumps(data, ensure_ascii=False) + "\n"
        )
        self.file.flush()

    def record_turn(
        self,
        game,
        player,
        action,
        action_type,
        hand_before,
        previous_play,
        previous_player,
        legal_count
    ):
        self.turn_count += 1

        hand_after = game.hands[player]

        self.write({
            "event": "turn",
            "turn": self.turn_count,
            "player": player,
            "team": "A" if player in (0, 2) else "B",

            "action_type": action_type,
            "action": serialize_cards(action),

            "hand_before": serialize_cards(hand_before),
            "hand_after": serialize_cards(hand_after),

            "hand_count_before": len(hand_before),
            "hand_count_after": len(hand_after),

            "previous_play": serialize_cards(previous_play),
            "previous_player": previous_player,

            "legal_move_count": legal_count,

            "finished_players": list(game.finished_players),
            "game_over": game.game_over
        })

    def finish(self, game):
        """收尾并关闭文件；重复调用是安全的。返回日志路径。"""
        if self.closed:
            return self.file_path

        self.write({
            "event": "game_end",
            "turn_count": self.turn_count,
            "finished_players": list(game.finished_players),
            "game_over": game.game_over,
            "time": datetime.now().isoformat()
        })

        self.file.close()
        self.closed = True

        return self.file_path
