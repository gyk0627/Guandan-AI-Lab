
import json
from pathlib import Path
from collections import defaultdict


def load_latest_game():
    folder = Path(__file__).resolve().parent

    files = sorted(
        folder.glob("game_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not files:
        raise FileNotFoundError("没有找到对局日志文件")

    path = files[0]
    events = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                events.append(json.loads(line))

    return path, events


def analyze_game():

    path, events = load_latest_game()

    turns = [
        event for event in events
        if event.get("event") == "turn"
    ]

    end_events = [
        event for event in events
        if event.get("event") == "game_end"
    ]

    if not turns:
        print("日志中没有行动记录。")
        return

    stats = defaultdict(lambda: {
        "plays": 0,
        "passes": 0,
        "cards_played": 0,
        "cards_at_start": 0,
        "cards_at_end": 0,
        "available_actions": 0,
        "pass_with_options": 0
    })

    print("=" * 65)
    print("GuanDan AI Lab - 自动对局复盘分析")
    print("=" * 65)

    print(f"日志文件：{path.name}")
    print(f"总行动次数：{len(turns)}")

    for event in turns:

        player = event["player"]
        data = stats[player]

        action_type = event["action_type"]

        before = event.get("hand_count_before", 0)
        after = event.get("hand_count_after", 0)
        legal_count = event.get("legal_move_count", 0)

        data["cards_at_start"] = before
        data["cards_at_end"] = after
        data["available_actions"] += legal_count

        if action_type == "play":

            data["plays"] += 1

            if isinstance(event.get("action"), list):
                data["cards_played"] += len(event["action"])

        elif action_type == "pass":

            data["passes"] += 1

            # 有合法候选动作却选择过牌
            if legal_count > 0:
                data["pass_with_options"] += 1

    print("\n一、玩家行动统计")
    print("-" * 65)

    for player in range(4):

        data = stats[player]
        team = "A队" if player in (0, 2) else "B队"

        total = data["plays"] + data["passes"]

        pass_rate = (
            data["passes"] / total * 100
            if total else 0
        )

        print(f"\n玩家 {player}（{team}）")
        print(f"出牌次数：{data['plays']}")
        print(f"过牌次数：{data['passes']}")
        print(f"过牌比例：{pass_rate:.1f}%")
        print(f"累计打出牌数：{data['cards_played']}")
        print(f"最后剩余手牌：{data['cards_at_end']}")

        print(
            "有合法候选动作却选择过牌："
            f"{data['pass_with_options']} 次"
        )

    print("\n二、可疑决策检查")
    print("-" * 65)

    suspicious = []

    for event in turns:

        if (
            event["action_type"] == "pass"
            and event.get("legal_move_count", 0) > 0
        ):
            suspicious.append(event)

    print(
        f"存在合法候选动作但选择过牌的次数："
        f"{len(suspicious)}"
    )

    if suspicious:

        print("\n前十条记录：")

        for event in suspicious[:10]:

            print(
                f"第 {event['turn']} 步 | "
                f"玩家 {event['player']} | "
                f"手牌 {event['hand_count_before']} 张 | "
                f"候选动作 {event['legal_move_count']} 个"
            )

    print("\n三、关键行动记录")
    print("-" * 65)

    for event in turns:

        if event["hand_count_after"] <= 3:

            print(
                f"第 {event['turn']} 步 | "
                f"玩家 {event['player']} | "
                f"{event['action_type']} | "
                f"剩余 {event['hand_count_after']} 张"
            )

    print("\n四、对局结果")
    print("-" * 65)

    if end_events:

        result = end_events[-1]

        print("最终名次：", result["finished_players"])
        print("总行动次数：", result["turn_count"])

        first = result["finished_players"][0]
        team = "A队" if first in (0, 2) else "B队"

        print("率先出完队伍：", team)

    else:
        print("没有找到完整的对局结束记录。")

    print("\n分析完成。")
    print("=" * 65)


if __name__ == "__main__":
    analyze_game()
