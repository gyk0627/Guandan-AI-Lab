"""对局数据采集（v2）。

与旧版采集器的区别：

1. **不再把每个候选动作的编码塞进 JSONL**。旧版 100 局就 19MB，按新编码器
   （65 维动作）会涨到几百 MB。现在只记录「决策时刻玩家能看到的全部信息 +
   实际选择」，训练前用引擎确定性地重算候选再编码（见 training/export_dataset.py）。
2. **可复现**：同 seed + 同 level + 同策略，产出的决策记录逐字节相同
   （采集时会自检，见 collect_dataset 的 verify_reproducible）。
3. **名次标签**：除了「率先出完的队伍」，还记录完整名次、队伍最佳名次、
   以及按规则换算出的升级数（第一&第二升 3 级、第一&第三升 2 级、第一&第四升 1 级）。
4. **级牌**：每局的 level 记进数据；默认按 2..A 轮转，覆盖全部 13 个级牌。

用法：

    .\\.venv\\Scripts\\python.exe -m training.collect_data --games 100
    .\\.venv\\Scripts\\python.exe -m training.collect_data --games 50 --level-mode none
"""

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

from game_engine.game_state import GameState
from game_engine.ranks import NORMAL_RANKS
from players.heuristic import choose_move
from training.serialize import cards_to_text, hand_to_text

MAX_STEPS = 2000
DATA_DIR = Path(__file__).resolve().parent / "data"


def teammate(player):
    return (player + 2) % 4


def team_of(player):
    return "A" if player in (0, 2) else "B"


def upgrade_amount(ranking, team):
    """按名次换算升几级。第一&第二升 3、第一&第三升 2、第一&第四升 1。"""
    positions = sorted(
        index + 1 for index, player in enumerate(ranking)
        if team_of(player) == team
    )

    if positions[0] != 1:
        return 0

    return {2: 3, 3: 2, 4: 1}[positions[1]]


def policy_name(policy):
    """策略的可序列化名字（字符串策略直接用，对象取 .name）。"""
    if isinstance(policy, str):
        return policy

    return getattr(policy, "name", type(policy).__name__)


def select_action(game, player, legal, rng, policy):
    """按策略选出动作；None 表示过牌。

    policy 可以是字符串（"heuristic" / "random"），
    也可以是带 ``choose(game, player, legal)`` 的对象——
    自我对弈时四家可能用不同策略（见 players/sampling.py 的 SeatPolicies）。
    """
    if isinstance(policy, str):
        if policy == "random":
            return rng.choice(legal) if legal else None

        return choose_move(
            game.hands[player],
            legal,
            rng=rng,
            game_state=game,
            player=player,
        )

    return policy.choose(game, player, legal)


def collect_one_game(seed, level=None, policy="heuristic"):
    """跑一局并返回 (决策记录列表, 结束记录)。"""
    game = GameState.new_game(seed=seed, level=level)
    rng = random.Random(seed + 1000)

    game_id = f"s{seed}-L{level or 'none'}"
    decisions = []
    step = 0

    while not game.game_over:
        step += 1

        if step > MAX_STEPS:
            raise RuntimeError(
                f"{game_id} 超过 {MAX_STEPS} 步，可能存在回合逻辑问题"
            )

        player = game.current_player
        hand = list(game.hands[player])
        last_play = (
            list(game.last_play)
            if game.last_play is not None
            else None
        )

        legal = game.get_legal_moves(player)

        # 候选顺序固定：先全部合法出牌，最后才是过牌
        candidates = list(legal)
        if last_play is not None:
            candidates.append(None)

        selected = select_action(game, player, legal, rng, policy)

        try:
            selected_index = candidates.index(selected)
        except ValueError:
            raise RuntimeError(
                f"{game_id} 第 {step} 步：策略给出了不在候选里的动作 {selected}"
            )

        decisions.append({
            "type": "decision",
            "game": game_id,
            "seed": seed,
            "level": level,
            "policy": policy_name(policy),
            "turn": step,
            "player": player,
            "team": team_of(player),
            "hand": hand_to_text(hand),
            "last_play": cards_to_text(last_play),
            "last_player": game.last_player,
            "pass_count": game.pass_count,
            "finished": list(game.finished_players),
            "hand_counts": [len(game.hands[i]) for i in range(4)],
            "num_candidates": len(candidates),
            "selected_index": selected_index,
            "action": cards_to_text(selected),
            "action_type": "pass" if selected is None else "play",
        })

        if selected is None:
            game.pass_turn(player)
        else:
            game.play(player, selected)

    ranking = list(game.finished_players)
    first_team = team_of(ranking[0])

    summary = {
        "type": "game",
        "game": game_id,
        "seed": seed,
        "level": level,
        "policy": policy_name(policy),
        "steps": step,
        "ranking": ranking,
        "first_out_team": first_team,
        "team_rank": {
            team: min(
                index + 1 for index, player in enumerate(ranking)
                if team_of(player) == team
            )
            for team in ("A", "B")
        },
        "level_up": {
            team: upgrade_amount(ranking, team)
            for team in ("A", "B")
        },
    }

    return decisions, summary


def dump_game(decisions, summary):
    """把一局序列化为 JSONL 行列表（去掉时间戳，保证可复现）。"""
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in decisions
    ]
    lines.append(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return lines


def pick_level(index, mode, fixed_level):
    if mode == "none":
        return None
    if mode == "fixed":
        return fixed_level
    return NORMAL_RANKS[index % len(NORMAL_RANKS)]


def collect_dataset(
    num_games=100,
    start_seed=1000,
    level_mode="cycle",
    fixed_level=None,
    policy="heuristic",
    output_path=None,
):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = DATA_DIR / f"games_{timestamp}.jsonl"
    else:
        output_path = Path(output_path)

    stats = {
        "games": 0,
        "decisions": 0,
        "pass": 0,
        "play": 0,
        "steps": 0,
        "level_up": {},
        "first_out_team": {},
    }

    with output_path.open("w", encoding="utf-8") as file:
        for index in range(num_games):
            seed = start_seed + index
            level = pick_level(index, level_mode, fixed_level)

            decisions, summary = collect_one_game(
                seed=seed, level=level, policy=policy
            )

            for line in dump_game(decisions, summary):
                file.write(line + "\n")

            stats["games"] += 1
            stats["decisions"] += len(decisions)
            stats["steps"] += summary["steps"]
            stats["first_out_team"][summary["first_out_team"]] = (
                stats["first_out_team"].get(summary["first_out_team"], 0) + 1
            )

            for record in decisions:
                stats[record["action_type"]] += 1

            if (index + 1) % 10 == 0 or index == num_games - 1:
                print(
                    f"对局 {index + 1:04d}/{num_games} | "
                    f"level={level or 'none'} | "
                    f"步数 {summary['steps']:4d} | "
                    f"累计样本 {stats['decisions']}"
                )

    manifest = {
        "file": output_path.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "num_games": stats["games"],
        "start_seed": start_seed,
        "level_mode": level_mode,
        "fixed_level": fixed_level,
        "policy": policy_name(policy),
        "decisions": stats["decisions"],
        "actions": {"pass": stats["pass"], "play": stats["play"]},
        "first_out_team": stats["first_out_team"],
        "avg_steps": round(stats["steps"] / max(stats["games"], 1), 2),
    }

    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("采集完成")
    print("=" * 60)
    print(f"对局数：{stats['games']}")
    print(f"决策样本：{stats['decisions']}")
    print(f"出牌/过牌：{stats['play']} / {stats['pass']}")
    print(f"平均步数：{manifest['avg_steps']}")
    print(f"数据文件：{output_path}")
    print(f"清单文件：{manifest_path}")

    return output_path, manifest


def verify_reproducible(seed=1000, level=None, policy="heuristic"):
    """同一 seed / level / 策略必须产出逐字节相同的记录。"""
    first = dump_game(*collect_one_game(seed, level, policy))
    second = dump_game(*collect_one_game(seed, level, policy))

    if first != second:
        raise RuntimeError("数据采集不可复现：两次运行结果不同")

    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="采集掼蛋对局数据（每行一条决策记录）"
    )
    parser.add_argument("--games", type=int, default=100, help="对局数量")
    parser.add_argument("--seed-start", type=int, default=1000, help="起始随机种子")
    parser.add_argument(
        "--level-mode",
        choices=("cycle", "fixed", "none"),
        default="cycle",
        help="级牌模式：cycle 按 2..A 轮转，fixed 固定，none 无级牌",
    )
    parser.add_argument("--level", default=None, help="fixed 模式下的级牌点数")
    parser.add_argument(
        "--policy",
        choices=("heuristic", "random"),
        default="heuristic",
        help="对局策略",
    )
    parser.add_argument("--out", default=None, help="输出文件路径")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只做可复现性自检，不采集",
    )

    args = parser.parse_args(argv)

    if args.check:
        verify_reproducible(args.seed_start, args.level, args.policy)
        print("可复现性自检通过。")
        return 0

    collect_dataset(
        num_games=args.games,
        start_seed=args.seed_start,
        level_mode=args.level_mode,
        fixed_level=args.level,
        policy=args.policy,
        output_path=args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
