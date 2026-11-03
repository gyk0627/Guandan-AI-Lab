"""把采集到的 JSONL 导出成训练用的 numpy 数组。

为什么要有这一层：

采集时只记录「玩家当时能看到的信息 + 实际动作」，不记录候选动作的编码。
导出时**按 seed 重放整局**，用引擎重新生成候选、重新编码。这样做有三个好处：

1. 数据文件小（100 局约 10MB，而不是几百 MB）。
2. 规则或编码器改了以后，只要重跑本脚本，旧对局会自动用新表示重新编码。
3. 重放过程本身就是一次完整性校验：重算出的候选数量、选中的动作、
   当下手牌，必须和采集时记录的完全一致，否则立刻报错。

输出 .npz：

    states        (N, STATE_DIM)            状态向量
    cand_flat     (总候选数, ACTION_DIM)     所有候选动作，展平存放
    cand_offsets  (N+1,)                    第 i 条样本的候选区间
    y_index       (N,)                      正确动作在候选区间内的下标
    hand_ranks    (N,)                      该玩家最终名次 1..4
    team_win      (N,)                      所在队伍是否率先出完（1/0）
    level_up      (N,)                      所在队伍升几级（0/1/2/3）
    is_pass       (N,)                      正确动作是否为过牌（1/0）
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from game_engine.game_state import GameState
from game_engine.legal_moves import generate_candidates, legal_moves
from game_engine.patterns import analyze_cards
from game_engine.ranks import natural_value, rank_of
from game_engine.wildcards import count_wildcards
from training.serialize import cards_to_text, text_to_cards, text_to_hand
from training.state_encoder import (
    ACTION_DIM,
    STATE_DIM,
    encode_action,
    encode_state,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


def equivalence_key(cards, level=None):
    """候选动作的「策略等价」标识。

    同一个键的候选，是**同一手牌的不同花色排列**——在规则上完全等价，
    只是手里留下哪张花色不同。启发式在这些等价候选之间是随机挑的，
    所以行为克隆的标签里这部分是噪声。

    键里保留三样东西，避免把真正不同的选择合并掉：
    * 牌型与主牌（大小关系不同就是不同的牌）；
    * 点数组合（3-4-5-6-7 和 4-5-6-7-8 不同）；
    * 用了几个逢人配（打出万能牌的代价不一样）。
    """
    if not cards:
        return ("pass",)

    info = analyze_cards(cards, level)

    if info is None:
        # 正常不会发生；真发生了就退化成「按具体牌区分」，避免错误合并
        return ("invalid",) + tuple(sorted(repr(card) for card in cards))

    ranks = tuple(sorted(natural_value(rank_of(card)) for card in cards))

    return (
        info["type"],
        info["main_value"],
        info["count"],
        ranks,
        count_wildcards(cards, level),
    )


def group_candidates(candidates, level=None):
    """给一条样本的候选动作编号：等价候选拿到同一个组号。"""
    mapping = {}
    groups = []

    for candidate in candidates:
        key = equivalence_key(candidate, level)

        if key not in mapping:
            mapping[key] = len(mapping)

        groups.append(mapping[key])

    return groups


def load_records(path):
    decisions = defaultdict(list)
    summaries = {}

    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            record = json.loads(line)

            if "state" in record:
                raise ValueError(
                    f"第 {line_number} 行是旧格式（自带 state 字段）。"
                    "旧数据已作废，请用 training.collect_data 重新采集。"
                )

            if record["type"] == "decision":
                decisions[record["game"]].append(record)
            else:
                summaries[record["game"]] = record

    return decisions, summaries


def build_candidates(game, player, last_play, last_player, level):
    """按引擎重算候选列表，过牌放在最后。

    必须和 GameState.get_legal_moves 完全一致：领出时没有过牌选项，
    其余情况下「全部合法出牌 + 最后一个过牌」。
    （2026-11-03 起可以压队友的牌，所以不再有「队友领出只能过牌」的例外。）
    """
    if last_play is None:
        candidates = list(generate_candidates(game.hands[player], level))
    else:
        candidates = list(legal_moves(game.hands[player], last_play, level))

    if last_play is not None:
        candidates.append(None)

    return candidates


def export(path, out_path=None, limit=None, verify=True, progress=None):
    decisions, summaries = load_records(path)

    if limit is not None:
        keys = sorted(decisions, key=lambda key: (decisions[key][0]["seed"], key))[:limit]
        decisions = {key: decisions[key] for key in keys}

    states = []
    cand_blocks = []
    cand_group_blocks = []
    cand_offsets = [0]
    y_index = []
    hand_ranks = []
    team_win = []
    level_up = []
    is_pass = []
    game_index = []
    game_order = []

    stats = Counter()
    problems = []
    total_games = len(decisions)

    for game_id in sorted(decisions, key=lambda key: key):
        records = decisions[game_id]
        summary = summaries.get(game_id)

        if summary is None:
            problems.append(f"{game_id}: 缺少对局结束记录")
            continue

        current_game_index = len(game_order)
        game_order.append(game_id)

        seed = records[0]["seed"]
        level = records[0]["level"]
        game = GameState.new_game(seed=seed, level=level)

        ranking = summary["ranking"]

        for record in records:
            player = record["player"]

            # 标签必须按「这条样本自己的队伍」算，不能用第一条记录的队伍
            team = record["team"]
            team_result = 1 if summary["first_out_team"] == team else 0
            upgrade = summary["level_up"][team]

            if game.current_player != player:
                raise RuntimeError(
                    f"{game_id} 第 {record['turn']} 步：重放后当前玩家是 "
                    f"{game.current_player}，记录里是 {player}"
                )

            if game.game_over:
                raise RuntimeError(f"{game_id} 第 {record['turn']} 步：对局已经结束")

            if verify:
                recorded_hand = text_to_hand(record["hand"])

                if recorded_hand != list(game.hands[player]):
                    raise RuntimeError(
                        f"{game_id} 第 {record['turn']} 步：重放手牌与记录不一致"
                    )

            last_play = (
                list(game.last_play)
                if game.last_play is not None
                else None
            )

            candidates = build_candidates(
                game, player, last_play, game.last_player, level
            )

            if verify and len(candidates) != record["num_candidates"]:
                raise RuntimeError(
                    f"{game_id} 第 {record['turn']} 步：候选数量 "
                    f"{len(candidates)} ≠ 记录 {record['num_candidates']}。"
                    "说明生成器和采集时的行为已经不一致。"
                )

            selected = None if record["action"] is None else text_to_cards(record["action"])
            index = record["selected_index"]

            if verify:
                if index >= len(candidates):
                    raise RuntimeError(
                        f"{game_id} 第 {record['turn']} 步：selected_index 越界"
                    )

                if candidates[index] != selected:
                    raise RuntimeError(
                        f"{game_id} 第 {record['turn']} 步："
                        f"候选[{index}] 与记录的动作为不一致"
                    )

            states.append(
                np.asarray(encode_state(game, player), dtype=np.float32)
            )

            # 存成「每条样本一个二维块」，最后再拼接。
            # 不要用 list of list of float：2000 局会产生 2.8 亿个 Python 对象。
            block = np.asarray(
                [encode_action(candidate, level) for candidate in candidates],
                dtype=np.float32,
            )
            cand_blocks.append(block)
            cand_group_blocks.append(
                np.asarray(group_candidates(candidates, level), dtype=np.int16)
            )
            cand_offsets.append(cand_offsets[-1] + len(block))

            y_index.append(index)
            hand_ranks.append(ranking.index(player) + 1)
            team_win.append(team_result)
            level_up.append(upgrade)
            is_pass.append(1 if selected is None else 0)
            game_index.append(current_game_index)

            stats["decisions"] += 1
            stats["pass" if selected is None else "play"] += 1
            stats["candidates"] += len(candidates)

            if selected is None:
                game.pass_turn(player)
            else:
                game.play(player, selected)

        stats["games"] += 1

        if not game.game_over:
            problems.append(f"{game_id}: 重放结束后对局没有结束")

        if progress is not None and (
            stats["games"] % 10 == 0 or stats["games"] == total_games
        ):
            progress(stats["games"], total_games, stats["decisions"])

    states = np.asarray(states, dtype=np.float32)

    if cand_blocks:
        cand_flat = np.concatenate(cand_blocks, axis=0)
        cand_groups = np.concatenate(cand_group_blocks, axis=0)
    else:
        cand_flat = np.zeros((0, ACTION_DIM), dtype=np.float32)
        cand_groups = np.zeros((0,), dtype=np.int16)

    cand_offsets = np.asarray(cand_offsets, dtype=np.int32)
    y_index = np.asarray(y_index, dtype=np.int32)
    hand_ranks = np.asarray(hand_ranks, dtype=np.int8)
    team_win = np.asarray(team_win, dtype=np.int8)
    level_up = np.asarray(level_up, dtype=np.int8)
    is_pass = np.asarray(is_pass, dtype=np.int8)
    game_index = np.asarray(game_index, dtype=np.int32)

    if states.ndim != 2 or states.shape[1] != STATE_DIM:
        raise RuntimeError(f"状态维度异常：{states.shape}")
    if cand_flat.ndim != 2 or cand_flat.shape[1] != ACTION_DIM:
        raise RuntimeError(f"动作维度异常：{cand_flat.shape}")

    meta = {
        "source": Path(path).name,
        "samples": int(states.shape[0]),
        "games": stats["games"],
        "state_dim": int(STATE_DIM),
        "action_dim": int(ACTION_DIM),
        "avg_candidates": round(stats["candidates"] / max(stats["decisions"], 1), 2),
        "max_candidates": int(np.diff(cand_offsets).max()) if len(cand_offsets) > 1 else 0,
        "pass_ratio": round(stats["pass"] / max(stats["decisions"], 1), 4),
        "rank_distribution": dict(sorted(Counter(hand_ranks.tolist()).items())),
        "team_win_ratio": round(float(team_win.mean()), 4),
        "level_up_distribution": dict(sorted(Counter(level_up.tolist()).items())),
        "games_list": game_order,
        "problems": problems,
    }

    out_path = Path(out_path) if out_path else Path(path).with_suffix(".npz")
    np.savez_compressed(
        out_path,
        states=states,
        cand_flat=cand_flat,
        cand_groups=cand_groups,
        cand_offsets=cand_offsets,
        y_index=y_index,
        hand_ranks=hand_ranks,
        team_win=team_win,
        level_up=level_up,
        is_pass=is_pass,
        game_index=game_index,
    )

    out_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 60)
    print("导出完成")
    print("=" * 60)
    print(f"样本数：{meta['samples']}（{meta['games']} 局）")
    print(f"状态维度：{STATE_DIM}   动作维度：{ACTION_DIM}")
    print(f"平均候选：{meta['avg_candidates']}   最大候选：{meta['max_candidates']}")
    print(f"过牌比例：{meta['pass_ratio']}")
    print(f"名次分布：{meta['rank_distribution']}")
    print(f"升几级分布：{meta['level_up_distribution']}")
    print(f"输出：{out_path}")

    if problems:
        print("\n发现问题：")
        for problem in problems[:20]:
            print("  -", problem)

    return out_path, meta


def pad_candidates(cand_flat, cand_offsets, max_width=None):
    """把展平的候选补成 (N, W, ACTION_DIM) + mask。

    注意：不要在全局做这件事。领出时一手 27 张牌的候选可以到 300+ 个，
    全局按最大宽度补边会让内存爆炸（3 万条样本就能吃掉几个 GB）。
    正确用法是**按 batch 内实际最大宽度补边**：给 max_width 传入本批最大值，
    或者用 np.diff(cand_offsets[i:j]).max()。
    """
    if len(cand_offsets) < 2:
        return (
            np.zeros((0, 0, ACTION_DIM), dtype=np.float32),
            np.zeros((0, 0), dtype=np.float32),
        )

    dim = cand_flat.shape[1] if cand_flat.ndim == 2 else ACTION_DIM
    lengths = np.diff(cand_offsets)
    width = int(max_width) if max_width is not None else int(lengths.max())
    count = len(lengths)

    padded = np.zeros((count, width, dim), dtype=np.float32)
    mask = np.zeros((count, width), dtype=np.float32)

    for row in range(count):
        start = cand_offsets[row]
        end = cand_offsets[row + 1]
        length = min(end - start, width)
        padded[row, :length] = cand_flat[start:start + length]
        mask[row, :length] = 1.0

    return padded, mask


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把采集的 JSONL 重放并导出成训练用 .npz"
    )
    parser.add_argument("path", nargs="?", help="JSONL 文件；省略时取 data 下最新")
    parser.add_argument("--out", default=None, help="输出 .npz 路径")
    parser.add_argument("--limit", type=int, default=None, help="只导出前 N 局（调试用）")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="跳过一致性校验（不要用于正式数据）",
    )

    args = parser.parse_args(argv)

    path = args.path

    if path is None:
        files = sorted(DATA_DIR.glob("games_*.jsonl"), key=lambda p: p.stat().st_mtime)

        if not files:
            raise FileNotFoundError(f"{DATA_DIR} 下没有 games_*.jsonl，请先采集")

        path = files[-1]

    print(f"数据文件：{path}")
    export(
        path,
        out_path=args.out,
        limit=args.limit,
        verify=not args.no_verify,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
