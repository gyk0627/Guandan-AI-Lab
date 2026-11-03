"""命令行入口与对抗评估器的 smoke 测试。

原则：测试里最多跑几局，慢的统计逻辑一律用假数据单测。
"""

import contextlib
import csv
import io
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import main as cli  # noqa: E402  先准备好 sys.path 再导入
from evaluation.benchmark import (  # noqa: E402
    run_benchmark,
    summarize_durations,
)
from evaluation.head_to_head import (  # noqa: E402
    GameTooLongError,
    RandomPolicy,
    create_policy,
    play_one_game,
    summarize_records,
    wilson_interval,
)


@pytest.fixture
def output_dir():
    """评估输出目录，测试结束后自动清理。

    直接建在仓库里而不是系统临时目录，
    是因为沙箱环境可能不允许在系统临时目录写文件。
    """

    base = ROOT / ".tmp_eval"
    base.mkdir(parents=True, exist_ok=True)

    directory = base / f"run_{uuid.uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=True)

    try:
        yield directory

    finally:
        shutil.rmtree(directory, ignore_errors=True)

        try:
            base.rmdir()
        except OSError:
            # 还有别的测试目录在用，留给下一次清理
            pass


def run_cli(argv):
    """在进程内调用 main()，返回 (退出码, 标准输出)。

    在进程内跑比起子进程快得多，
    也避免沙箱环境下子进程管道被拦截的问题。
    """

    buffer = io.StringIO()
    exit_code = 0

    with contextlib.redirect_stdout(buffer):
        try:
            result = cli.main(list(argv))
            exit_code = 0 if result is None else int(result)

        except SystemExit as error:
            exit_code = 0 if error.code is None else int(error.code)

    return exit_code, buffer.getvalue()


# ==================== 命令行 smoke 测试 ====================

def test_main_help_lists_all_subcommands():
    code, output = run_cli(["--help"])

    assert code == 0

    for name in ("play", "bench", "evaluate", "collect", "test"):
        assert name in output


def test_main_without_arguments_prints_help():
    code, output = run_cli([])

    assert code == 0
    assert "子命令" in output
    assert "play" in output
    assert "evaluate" in output


def test_play_seed_one_without_log():
    before = {path.name for path in (ROOT / "replay").glob("*.jsonl")}

    code, output = run_cli(["play", "--seed", "1", "--no-log"])

    after = {path.name for path in (ROOT / "replay").glob("*.jsonl")}

    assert code == 0
    assert "第1名" in output
    assert "总行动次数" in output
    assert "率先出完牌的队伍" in output
    # --no-log 不应该产生新的 jsonl
    assert before == after


def test_play_subcommand_help():
    code, output = run_cli(["play", "--help"])

    assert code == 0
    assert "--seed" in output
    assert "--no-log" in output


def test_bench_cli_one_game():
    code, output = run_cli(["bench", "--games", "1", "--seed-start", "9"])

    assert code == 0
    assert "平均步数" in output
    assert "每局耗时" in output


def test_collect_help_is_available():
    code, output = run_cli(["collect", "--help"])

    assert code == 0
    assert "training" in output


def test_collect_kwargs_follow_target_signature():
    """collect 不写死参数名：参数按目标函数签名动态转换。"""

    def fake_collect(num_games=1, start_seed=1000, tag="x", verbose=False):
        return None

    kwargs = cli._collect_kwargs(
        fake_collect,
        [
            "--num-games", "3",
            "--start-seed=7",
            "--tag", "abc",
            "--verbose",
            "--unknown", "9",
        ],
    )

    assert kwargs == {
        "num_games": 3,
        "start_seed": 7,
        "tag": "abc",
        "verbose": True,
    }


def test_collect_kwargs_support_argv_style_main():
    """目标 main 若接收 argv，则剩余参数原样透传。"""

    def fake_main(argv=None):
        return 0

    kwargs = cli._collect_kwargs(fake_main, ["--games", "2"])

    assert kwargs == {"argv": ["--games", "2"]}


def test_evaluate_help_is_forwarded():
    code, output = run_cli(["evaluate", "--help"])

    assert code == 0
    assert "--opponent" in output
    assert "--games" in output


# ==================== 评估器 smoke 测试 ====================

def test_evaluate_two_pairs_writes_four_rows(output_dir):
    code, output = run_cli([
        "evaluate",
        "--games", "2",
        "--seed-start", "1",
        "--opponent", "random",
        "--output-dir", str(output_dir),
    ])

    assert code == 0
    assert "95% Wilson 置信区间" in output

    csv_files = list(output_dir.glob("head_to_head_*.csv"))
    assert len(csv_files) == 1

    with csv_files[0].open(
        newline="",
        encoding="utf-8-sig",
    ) as file:
        rows = list(csv.DictReader(file))

    # 2 组 × 2 局 = 4 行
    assert len(rows) == 4

    # 同一 seed 两局，且策略 A 换了座位
    assert rows[0]["seed"] == rows[1]["seed"] == "1"
    assert rows[2]["seed"] == rows[3]["seed"] == "2"
    assert {rows[0]["a_team"], rows[1]["a_team"]} == {"A", "B"}

    # 胜负口径：a_won 与 winner_team / a_team 一致
    for row in rows:
        assert row["a_won"] in ("True", "False")
        assert (row["a_won"] == "True") == (
            row["winner_team"] == row["a_team"]
        )
        assert int(row["steps"]) > 0


def test_evaluate_json_summary(output_dir):
    code, output = run_cli([
        "evaluate",
        "--games", "1",
        "--seed-start", "5",
        "--json",
        "--output-dir", str(output_dir),
    ])

    assert code == 0

    summary = json.loads(output)

    assert summary["total_games"] == 2
    assert summary["pairs"] == 1
    assert summary["strategy"] == "heuristic"
    assert summary["opponent"] == "random"
    assert summary["strategy_wins"] + summary["opponent_wins"] == 2
    assert (
        summary["wilson_low"]
        <= summary["win_rate"]
        <= summary["wilson_high"]
    )
    assert Path(summary["csv_path"]).exists()


def test_play_one_game_raises_when_too_long():
    with pytest.raises(GameTooLongError):
        play_one_game(
            seed=1,
            strategy_a="heuristic",
            strategy_b="heuristic",
            a_team="A",
            max_steps=5,
        )


def test_create_policy_accepts_factory_name_and_object():
    from_factory = create_policy(
        lambda seed: RandomPolicy(seed),
        seed=7,
    )
    assert hasattr(from_factory, "choose")

    existing = RandomPolicy(9)
    assert create_policy(existing, seed=0) is existing

    from_name = create_policy("random", seed=3)
    assert from_name.name == "random"

    with pytest.raises(ValueError):
        create_policy("not-a-strategy")

    with pytest.raises(TypeError):
        create_policy(123)


def test_evaluate_stops_when_game_too_long(output_dir):
    """防呆：单局超过步数上限时返回非零，而不是静默卡死。"""

    code, _ = run_cli([
        "evaluate",
        "--games", "1",
        "--max-steps", "5",
        "--output-dir", str(output_dir),
    ])

    assert code == 1
    assert list(output_dir.glob("*.csv")) == []


# ==================== Wilson 区间单测 ====================

@pytest.mark.parametrize(
    "wins,total,low,high",
    [
        # 0/10 与 10/10 是 Wilson 区间最典型的边界
        (0, 10, 0.0, 0.2776),
        (10, 10, 0.7224, 1.0),
        (5, 10, 0.2366, 0.7634),
        (1, 10, 0.0179, 0.4042),
        (0, 1, 0.0, 0.7935),
        (1, 1, 0.2065, 1.0),
    ],
)
def test_wilson_interval_reference_values(wins, total, low, high):
    lower, upper = wilson_interval(wins, total)

    assert lower == pytest.approx(low, abs=1e-4)
    assert upper == pytest.approx(high, abs=1e-4)
    assert 0.0 <= lower <= upper <= 1.0


def test_wilson_interval_edge_cases():
    # 没有样本时返回完全不确定的区间
    assert wilson_interval(0, 0) == (0.0, 1.0)

    with pytest.raises(ValueError):
        wilson_interval(1, 0)

    with pytest.raises(ValueError):
        wilson_interval(-1, 10)

    with pytest.raises(ValueError):
        wilson_interval(11, 10)

    with pytest.raises(ValueError):
        wilson_interval(1, -1)


# ==================== 统计逻辑假数据单测 ====================

def make_record(pair, a_team, a_won, steps=80, seconds=0.1):
    """构造一条假对局记录，避免为了统计真的跑对局。"""

    return {
        "pair": pair,
        "a_team": a_team,
        "a_won": a_won,
        "steps": steps,
        "seconds": seconds,
    }


def test_summarize_records_with_fake_data():
    records = [
        make_record(1, "A", True, steps=60, seconds=0.2),
        make_record(1, "B", True, steps=80, seconds=0.4),
        make_record(2, "A", False, steps=100, seconds=0.6),
        make_record(2, "B", True, steps=100, seconds=0.8),
    ]

    summary = summarize_records(records)

    assert summary["total_games"] == 4
    assert summary["strategy_wins"] == 3
    assert summary["opponent_wins"] == 1
    assert summary["win_rate"] == pytest.approx(0.75)
    assert summary["avg_steps"] == pytest.approx(85.0)
    assert summary["total_seconds"] == pytest.approx(2.0)
    assert summary["seconds_per_game"] == pytest.approx(0.5)

    low, high = wilson_interval(3, 4)
    assert summary["wilson_low"] == pytest.approx(low)
    assert summary["wilson_high"] == pytest.approx(high)

    assert summary["by_team"]["A"]["games"] == 2
    assert summary["by_team"]["A"]["wins"] == 1
    assert summary["by_team"]["A"]["win_rate"] == pytest.approx(0.5)
    assert summary["by_team"]["B"]["wins"] == 2

    assert summary["pair_outcomes"]["sweep_win"] == 1
    assert summary["pair_outcomes"]["split"] == 1
    assert summary["pair_outcomes"]["sweep_loss"] == 0


def test_summarize_records_rejects_empty():
    with pytest.raises(ValueError):
        summarize_records([])


def test_summarize_durations_with_fake_data():
    stats = summarize_durations([0.4, 0.1, 0.3, 0.2])

    assert stats["count"] == 4
    assert stats["min"] == pytest.approx(0.1)
    assert stats["max"] == pytest.approx(0.4)
    assert stats["median"] == pytest.approx(0.25)
    assert stats["mean"] == pytest.approx(0.25)
    assert stats["total"] == pytest.approx(1.0)

    # 奇数个样本时取中间那个
    assert summarize_durations([0.3, 0.1, 0.2])["median"] == pytest.approx(0.2)

    empty = summarize_durations([])
    assert empty["count"] == 0
    assert empty["median"] == 0.0


def test_benchmark_two_games_smoke():
    result = run_benchmark(
        num_games=2,
        seed_start=3,
        verbose=False,
    )

    assert len(result["games"]) == 2
    assert result["avg_steps"] > 0
    assert result["durations"]["count"] == 2
    assert (
        result["durations"]["min"]
        <= result["durations"]["median"]
        <= result["durations"]["max"]
    )
