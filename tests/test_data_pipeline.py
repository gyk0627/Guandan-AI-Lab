"""数据管线测试：序列化、升级换算、采集可复现、导出与补边。"""

import json
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest

from game_engine.ranks import BIG_JOKER, SMALL_JOKER
from training import collect_data
from training.export_dataset import export, pad_candidates
from training.serialize import (
    card_to_text,
    cards_to_text,
    text_to_card,
    text_to_cards,
)
from training.state_encoder import ACTION_DIM, STATE_DIM

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    """测试用的临时目录。

    不能用 pytest 的 tmp_path：本机沙箱里系统 TEMP 目录不可写，
    所以在仓库内的 .test_tmp 下自建，结束时清理。
    """
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.mark.parametrize(
    "card,text",
    [
        (("S", "3"), "S:3"),
        (("H", "10"), "H:10"),
        (("D", "A"), "D:A"),
        (SMALL_JOKER, "SJ"),
        (BIG_JOKER, "BJ"),
    ],
)
def test_serialize_round_trip(card, text):
    assert card_to_text(card) == text
    assert text_to_card(text) == card


def test_spade_jack_does_not_collide_with_small_joker():
    """黑桃 J 和小王都写着 SJ 的话，重放会把手牌搞错。"""
    spade_jack = ("S", "J")

    assert card_to_text(spade_jack) != card_to_text(SMALL_JOKER)
    assert text_to_card(card_to_text(spade_jack)) == spade_jack
    assert text_to_card(card_to_text(SMALL_JOKER)) == SMALL_JOKER


def test_text_to_card_rejects_unknown():
    with pytest.raises(ValueError):
        text_to_card("XJ")
    with pytest.raises(ValueError):
        text_to_card("S")


def test_serialize_lists_round_trip():
    cards = [("S", "3"), ("H", "10"), "SJ", ("C", "A")]

    assert text_to_cards(cards_to_text(cards)) == cards


def test_upgrade_amount():
    # 第一、第二 -> 升 3 级
    assert collect_data.upgrade_amount([0, 2, 1, 3], "A") == 3
    # 第一、第三 -> 升 2 级
    assert collect_data.upgrade_amount([0, 1, 2, 3], "A") == 2
    # 第一、第四 -> 升 1 级
    assert collect_data.upgrade_amount([0, 1, 3, 2], "A") == 1
    # 没拿到第一 -> 0
    assert collect_data.upgrade_amount([1, 3, 0, 2], "A") == 0


def test_collect_one_game_is_deterministic():
    first = collect_data.dump_game(*collect_data.collect_one_game(seed=1000))
    second = collect_data.dump_game(*collect_data.collect_one_game(seed=1000))

    assert first == second


def test_collect_one_game_records_are_consistent():
    decisions, summary = collect_data.collect_one_game(seed=1001, level="2")

    assert len(decisions) == summary["steps"]
    assert summary["type"] == "game"
    assert sorted(summary["ranking"]) == [0, 1, 2, 3]
    assert all(record["type"] == "decision" for record in decisions)
    assert decisions[0]["player"] == 0
    assert decisions[0]["level"] == "2"

    for record in decisions:
        assert 0 <= record["selected_index"] < record["num_candidates"]
        assert record["action_type"] in ("play", "pass")
        if record["last_play"] is None:
            assert record["action_type"] == "play"


def test_partner_lead_keeps_play_options():
    """队友领出时，候选里既有能压的牌，也有过牌。

    2026-11-03 负责人确认可以压队友，所以这里不再出现「候选只有过牌」。
    """
    found = False

    for seed in range(1003, 1020):
        decisions, _ = collect_data.collect_one_game(seed=seed, level="2")

        for record in decisions:
            if (
                record["last_player"] is not None
                and (record["player"] + 2) % 4 == record["last_player"]
                and record["num_candidates"] > 1
            ):
                found = True

        if found:
            break

    assert found, "这 17 局里没有出现「队友领出、自己还能压」的情形"


def test_game_lines_are_valid_json():
    decisions, summary = collect_data.collect_one_game(seed=1002)

    for line in collect_data.dump_game(decisions, summary):
        json.loads(line)


def test_export_one_game(workdir):
    path = workdir / "games_test.jsonl"
    decisions, summary = collect_data.collect_one_game(seed=1003, level="2")

    path.write_text(
        "\n".join(collect_data.dump_game(decisions, summary)) + "\n",
        encoding="utf-8",
    )

    out, meta = export(path, out_path=workdir / "out.npz", limit=1)

    data = np.load(out)

    assert data["states"].shape == (len(decisions), STATE_DIM)
    assert data["cand_flat"].shape[1] == ACTION_DIM
    assert data["y_index"].shape == (len(decisions),)
    assert meta["samples"] == len(decisions)
    assert meta["problems"] == []
    assert 0 < meta["pass_ratio"] < 1
    assert meta["avg_candidates"] >= 1

    offsets = data["cand_offsets"]
    assert offsets[0] == 0
    assert offsets[-1] == data["cand_flat"].shape[0]
    assert np.all(np.diff(offsets) >= 1)

    for row in range(len(decisions)):
        assert 0 <= data["y_index"][row] < np.diff(offsets)[row]


def test_export_labels_are_per_record(workdir):
    """B 队样本的胜负标签不能照抄 A 队。"""
    path = workdir / "games_labels.jsonl"
    decisions, summary = collect_data.collect_one_game(seed=1004, level="5")

    path.write_text(
        "\n".join(collect_data.dump_game(decisions, summary)) + "\n",
        encoding="utf-8",
    )

    out, _ = export(path, out_path=workdir / "labels.npz", limit=1)
    data = np.load(out)

    winner = summary["first_out_team"]
    teams = [record["team"] for record in decisions]

    for index, team in enumerate(teams):
        assert data["team_win"][index] == (1 if team == winner else 0)
        assert data["is_pass"][index] == (
            1 if decisions[index]["action_type"] == "pass" else 0
        )


def test_export_detects_candidate_drift(workdir):
    """候选数量被篡改时必须报错，而不是静默产出错位标签。"""
    path = workdir / "games_drift.jsonl"
    decisions, summary = collect_data.collect_one_game(seed=1005, level="2")

    decisions[3]["num_candidates"] += 1

    path.write_text(
        "\n".join(collect_data.dump_game(decisions, summary)) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        export(path, out_path=workdir / "drift.npz", limit=1)


def test_pad_candidates():
    flat = np.arange(12, dtype=np.float32).reshape(6, 2)
    offsets = np.array([0, 2, 6], dtype=np.int32)

    padded, mask = pad_candidates(flat, offsets)

    assert padded.shape == (2, 4, 2)
    assert mask.tolist() == [[1, 1, 0, 0], [1, 1, 1, 1]]
    assert padded[1, 3].tolist() == [10, 11]


def test_pad_candidates_with_explicit_width():
    """按 batch 指定宽度，避免全局按最大值补边。"""
    flat = np.arange(6, dtype=np.float32).reshape(3, 2)
    offsets = np.array([0, 1, 3], dtype=np.int32)

    padded, mask = pad_candidates(flat, offsets, max_width=2)

    assert padded.shape == (2, 2, 2)
    assert mask.tolist() == [[1, 0], [1, 1]]


def test_export_rejects_stale_format(workdir):
    path = workdir / "old.jsonl"
    path.write_text(
        json.dumps({"type": "decision", "state": [0] * 58}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        export(path, out_path=workdir / "x.npz")


# ==================== 并行导出（tools/parallel_export.py） ====================


def test_parallel_export_group_by_game_keeps_order(workdir):
    from tools.parallel_export import group_by_game

    path = workdir / "g.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"game": game, "step": step})
            for game, step in [(2, 0), (1, 0), (2, 1), (1, 1), (2, 2)]
        )
        + "\n",
        encoding="utf-8",
    )

    games = group_by_game(path)

    assert list(games) == [2, 1]
    assert [json.loads(line)["step"] for line in games[2]] == [0, 1, 2]
    assert [json.loads(line)["step"] for line in games[1]] == [0, 1]


def test_parallel_export_split_is_contiguous_and_complete():
    """按对局 id 排序连续切分：合起来的行序必须与单进程导出完全一致。"""
    from tools.parallel_export import split_sorted

    games = {game: [json.dumps({"game": game})] * 2 for game in [7, 3, 9, 1, 5, 2]}
    buckets = split_sorted(games, workers=4)

    flat = [game for bucket in buckets for game, _lines in bucket]
    assert flat == sorted(games), "分片拼接顺序必须等于对局 id 升序"
    assert sorted(flat) == sorted(games), "不能漏局、不能重复"
    assert all(len(bucket) <= 2 for bucket in buckets)


def test_merge_renumbers_game_index_contiguously_two_parts(workdir):
    """回归：合并两份时 game_index 偏移曾逐份翻倍（0..2 + 0..1 变成 0..2 + 3..4 才对）。"""
    from training.merge_datasets import merge

    def make(path, games):
        samples = games * 2
        np.savez_compressed(
            path,
            states=np.zeros((samples, 4), dtype=np.float32),
            cand_flat=np.ones((samples, 2), dtype=np.float32),
            cand_offsets=np.arange(samples + 1, dtype=np.int32),
            y_index=np.zeros(samples, dtype=np.int64),
            hand_ranks=np.zeros(samples, dtype=np.int64),
            team_win=np.zeros(samples, dtype=np.int8),
            level_up=np.zeros(samples, dtype=np.int8),
            is_pass=np.zeros(samples, dtype=np.int8),
            game_index=np.repeat(np.arange(games), 2).astype(np.int64),
        )
        return path

    out, meta = merge(
        [make(workdir / "a.npz", 3), make(workdir / "b.npz", 2)],
        out_path=workdir / "m.npz",
    )

    assert meta["games"] == 5
    assert np.load(out)["game_index"].tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
