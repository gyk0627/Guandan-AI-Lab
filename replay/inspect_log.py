
import json
from pathlib import Path

files = sorted(
    Path(__file__).resolve().parent.glob("game_*.jsonl"),
    key=lambda p: p.stat().st_mtime,
    reverse=True
)

if not files:
    print("没有找到对局日志。")
    raise SystemExit

path = files[0]

events = []

with path.open("r", encoding="utf-8") as file:
    for line in file:
        events.append(json.loads(line))

turns = [x for x in events if x["event"] == "turn"]

print("=" * 55)
print("GuanDan AI Lab - 对局日志检查")
print("=" * 55)

print("日志文件：", path.name)
print("行动总数：", len(turns))

for item in turns[:10]:
    print("-" * 55)
    print(
        f"第 {item['turn']} 轮 | "
        f"玩家 {item['player']} | "
        f"队伍 {item['team']}"
    )
    print("行动：", item["action_type"])
    print("出牌：", item["action"])
    print(
        f"手牌数量：{item['hand_count_before']} "
        f"-> {item['hand_count_after']}"
    )
    print("当时合法动作数量：", item["legal_move_count"])

print("\n日志检查完成。")
