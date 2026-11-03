
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "strategy_comparison_v2.csv"


def load_results():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"没有找到实验数据：{CSV_PATH}\n"
            "请先运行 python -m evaluation.compare_strategies"
        )

    with CSV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        return list(csv.DictReader(file))


def analyze():
    results = load_results()

    if not results:
        print("实验数据为空。")
        return

    team_data = defaultdict(list)
    seed_data = defaultdict(list)

    for row in results:
        team = row["heuristic_team"]
        seed = int(row["seed"])
        won = row["heuristic_won"].strip().lower() == "true"
        steps = int(row["steps"])

        team_data[team].append({
            "won": won,
            "steps": steps
        })

        seed_data[seed].append({
            "team": team,
            "won": won,
            "steps": steps
        })

    total = len(results)
    wins = sum(
        1 for row in results
        if row["heuristic_won"].strip().lower() == "true"
    )

    print("=" * 60)
    print("GuanDan AI Lab - 策略稳定性分析")
    print("=" * 60)

    print(f"\n总对局数：{total}")
    print(f"启发式 AI 获胜：{wins}")
    print(f"整体胜率：{wins / total * 100:.2f}%")

    print("\n一、队伍位置分析")
    print("-" * 60)

    for team in ("A", "B"):
        data = team_data[team]

        if not data:
            continue

        team_wins = sum(x["won"] for x in data)
        rate = team_wins / len(data) * 100
        avg_steps = mean(x["steps"] for x in data)

        print(
            f"{team}队："
            f"{team_wins}/{len(data)} 胜，"
            f"胜率 {rate:.2f}%，"
            f"平均行动次数 {avg_steps:.2f}"
        )

    print("\n二、同种子交换队伍分析")
    print("-" * 60)

    both_win = 0
    split = 0
    both_lose = 0
    incomplete = 0

    for seed, games in sorted(seed_data.items()):
        if len(games) != 2:
            incomplete += 1
            continue

        outcomes = [x["won"] for x in games]

        if all(outcomes):
            both_win += 1
        elif not any(outcomes):
            both_lose += 1
        else:
            split += 1

    paired = both_win + split + both_lose

    print(f"完整种子组：{paired}")
    print(f"两场都赢：{both_win}")
    print(f"一胜一负：{split}")
    print(f"两场都输：{both_lose}")
    print(f"不完整种子组：{incomplete}")

    print("\n三、失败对局检查")
    print("-" * 60)

    losses = [
        row for row in results
        if row["heuristic_won"].strip().lower() != "true"
    ]

    print(f"失败场数：{len(losses)}")

    for row in losses[:20]:
        print(
            f"种子 {row['seed']} | "
            f"启发式在 {row['heuristic_team']} 队 | "
            f"行动次数 {row['steps']} | "
            f"最终名次 {row['ranking']}"
        )

    if len(losses) > 20:
        print(f"...另外还有 {len(losses) - 20} 场失败对局")

    print("\n四、行动次数统计")
    print("-" * 60)

    all_steps = [int(row["steps"]) for row in results]

    print(f"最少行动次数：{min(all_steps)}")
    print(f"最多行动次数：{max(all_steps)}")
    print(f"平均行动次数：{mean(all_steps):.2f}")

    print("\n分析完成。")
    print("=" * 60)


if __name__ == "__main__":
    analyze()
