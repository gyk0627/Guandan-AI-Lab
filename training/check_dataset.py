"""采集数据（v2 JSONL）的结构校验。

只做**不依赖引擎**的结构检查，跑得很快，适合采完立刻扫一遍：

* 每条记录的类型（decision / game）与字段是否齐全；
* 一局之内 level / seed / policy 是否一致；
* 名次是不是 0..3 的一个排列、每局正好四个名次；
* selected_index 是否落在候选数量范围内；
* action_type 与 action 是否自洽（过牌只能在没有领出牌时之外出现）；
* 候选数量是否 >= 1。

**完整的语义校验（重放 + 候选重算 + 标签对齐）由 training/export_dataset.py 负责**，
那一步会真正调用引擎，能抓出规则变动导致的错位。这里只负责"文件本身没坏"。
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

REQUIRED_DECISION_FIELDS = (
    "game", "seed", "level", "policy", "turn", "player", "team",
    "hand", "last_play", "last_player", "pass_count", "finished",
    "hand_counts", "num_candidates", "selected_index", "action",
    "action_type",
)

REQUIRED_GAME_FIELDS = (
    "game", "seed", "level", "policy", "steps", "ranking",
    "first_out_team", "team_rank", "level_up",
)


def check_file(path):
    path = Path(path)

    decisions = defaultdict(list)
    summaries = {}
    errors = []
    stats = Counter()

    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(f"第 {line_number} 行不是合法 JSON：{error}")
                continue

            stats[record.get("type", "unknown")] += 1

            if record.get("type") == "decision":
                missing = [
                    field for field in REQUIRED_DECISION_FIELDS
                    if field not in record
                ]

                if missing:
                    errors.append(f"第 {line_number} 行缺字段：{missing}")
                    continue

                decisions[record["game"]].append(record)

            elif record.get("type") == "game":
                missing = [
                    field for field in REQUIRED_GAME_FIELDS
                    if field not in record
                ]

                if missing:
                    errors.append(f"第 {line_number} 行缺字段：{missing}")
                    continue

                if record["game"] in summaries:
                    errors.append(f"第 {line_number} 行：对局 {record['game']} 结束记录重复")

                summaries[record["game"]] = record

            else:
                errors.append(f"第 {line_number} 行：未知记录类型 {record.get('type')}")

    for game_id, records in decisions.items():
        summary = summaries.get(game_id)

        if summary is None:
            errors.append(f"{game_id}: 缺少结束记录")
            continue

        if len(records) != summary["steps"]:
            errors.append(
                f"{game_id}: 决策记录 {len(records)} 条，但 steps={summary['steps']}"
            )

        ranking = summary["ranking"]

        if sorted(ranking) != [0, 1, 2, 3]:
            errors.append(f"{game_id}: 名次不是 0..3 的排列：{ranking}")

        # 队伍最佳名次只有两种合法形态：
        # 赢家 1、队友 2 -> 对方最佳 3（双下）；赢家 1、队友 3/4 -> 对方最佳 2
        team_ranks = sorted(summary["team_rank"].values())

        if team_ranks not in ([1, 2], [1, 3]):
            errors.append(f"{game_id}: team_rank 异常：{summary['team_rank']}")

        # 队名与实际名次必须对得上
        for team, best in summary["team_rank"].items():
            players = (0, 2) if team == "A" else (1, 3)
            actual = min(ranking.index(player) + 1 for player in players)

            if actual != best:
                errors.append(
                    f"{game_id}: team_rank[{team}]={best}，但实际最佳名次是 {actual}"
                )

        if summary["first_out_team"] not in ("A", "B"):
            errors.append(f"{game_id}: first_out_team 异常：{summary['first_out_team']}")

        for record in records:
            for field in ("seed", "level", "policy"):
                if record[field] != summary[field]:
                    errors.append(
                        f"{game_id} 第 {record['turn']} 步："
                        f"{field} 与结束记录不一致"
                    )

            if not 0 <= record["selected_index"] < record["num_candidates"]:
                errors.append(
                    f"{game_id} 第 {record['turn']} 步：selected_index 越界"
                )

            if record["num_candidates"] < 1:
                errors.append(f"{game_id} 第 {record['turn']} 步：候选数量为 0")

            if record["action_type"] == "pass":
                if record["action"] is not None:
                    errors.append(f"{game_id} 第 {record['turn']} 步：过牌却带了牌")
                if record["last_play"] is None:
                    errors.append(f"{game_id} 第 {record['turn']} 步：领出阶段不能过牌")
            elif record["action_type"] == "play":
                if not record["action"]:
                    errors.append(f"{game_id} 第 {record['turn']} 步：出牌却没有牌")
            else:
                errors.append(f"{game_id} 第 {record['turn']} 步：未知动作类型")

            if sum(record["hand_counts"]) > 108:
                errors.append(f"{game_id} 第 {record['turn']} 步：手牌总数超过 108")

            if len(record["hand"]) != record["hand_counts"][record["player"]]:
                errors.append(
                    f"{game_id} 第 {record['turn']} 步：手牌长度与 hand_counts 不一致"
                )

    return {
        "file": path.name,
        "games": len(summaries),
        "decisions": sum(len(records) for records in decisions.values()),
        "errors": errors,
        "stats": stats,
    }


def report(result):
    print("=" * 66)
    print("GuanDan AI Lab - 采集数据校验")
    print("=" * 66)
    print(f"文件：{result['file']}")
    print(f"对局：{result['games']}   决策：{result['decisions']}")
    print(f"记录类型：{dict(result['stats'])}")

    if result["errors"]:
        print(f"\n发现 {len(result['errors'])} 处问题（最多显示 30 条）：")
        for error in result["errors"][:30]:
            print("  -", error)
        print("\n结构校验未通过。")
        return 1

    print("\n结构校验通过。")
    print("提示：结构正确不代表语义正确，正式数据请再跑一次")
    print("      .\\.venv\\Scripts\\python.exe -m training.export_dataset")
    print("=" * 66)
    return 0


def latest_file():
    files = sorted(DATA_DIR.glob("games_*.jsonl"), key=lambda p: p.stat().st_mtime)

    if not files:
        raise FileNotFoundError(f"{DATA_DIR} 下没有 games_*.jsonl，请先采集")

    return files[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="校验采集数据文件的结构")
    parser.add_argument("path", nargs="?", help="JSONL 文件；省略时取 data 下最新")
    args = parser.parse_args(argv)

    path = args.path or latest_file()
    return report(check_file(path))


if __name__ == "__main__":
    raise SystemExit(main())
