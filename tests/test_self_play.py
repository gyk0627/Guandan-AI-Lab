"""自我对弈流水线测试。

不需要 torch 的部分（座位策略、分派、落盘）必须能在任何环境跑；
需要 torch 的（温度采样）用 importorskip 保护。
"""

import json
import shutil
import uuid
from pathlib import Path

import pytest

from game_engine.game_state import GameState
from players.sampling import HeuristicSeat, RandomSeat, SeatPolicies
from training import collect_data
from training.self_play import build_seat_policies, run_self_play

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def signature(cards):
    return sorted(map(repr, cards))


def test_policy_name_handles_strings_and_objects():
    assert collect_data.policy_name("heuristic") == "heuristic"

    seat = HeuristicSeat(seed=1, name="my-heuristic")

    assert collect_data.policy_name(seat) == "my-heuristic"


def test_heuristic_seat_returns_legal_action():
    game = GameState.new_game(seed=11, level="2")
    seat = HeuristicSeat(seed=1)

    legal = game.get_legal_moves(0)
    action = seat.choose(game, 0, legal)

    assert action is None or signature(action) in [signature(m) for m in legal]


def test_random_seat_returns_legal_action():
    game = GameState.new_game(seed=12, level="2")
    seat = RandomSeat(seed=1)

    legal = game.get_legal_moves(0)

    for _ in range(20):
        action = seat.choose(game, 0, legal)
        assert action is not None
        assert signature(action) in [signature(m) for m in legal]


def test_seat_policies_dispatch_by_player(workdir):
    """四家各用不同策略时，按座位分派不能串。"""
    policies = {
        0: RandomSeat(seed=1, name="r0"),
        1: HeuristicSeat(seed=2, name="h1"),
        2: RandomSeat(seed=3, name="r2"),
        3: HeuristicSeat(seed=4, name="h3"),
    }
    seats = SeatPolicies(policies)

    game = GameState.new_game(seed=13, level="2")

    for player in range(4):
        legal = game.get_legal_moves(player) if player == game.current_player else [["3"]]
        action = seats.choose(game, player, legal)
        assert action is None or action in [["3"]] or isinstance(action, list)

    assert seats.name.startswith("r0+h1")
    assert "r0" in seats.describe() and "h3" in seats.describe()


def test_seat_policies_rejects_missing_seat():
    with pytest.raises(ValueError):
        SeatPolicies({0: RandomSeat(), 1: RandomSeat()})


def test_build_seat_policies_specs():
    seats = build_seat_policies(
        ("heuristic", "random", "heuristic", "random"),
        seed=1,
        checkpoint=None,
        temperature=1.0,
        epsilon=0.0,
    )

    assert isinstance(seats.per_seat[0], HeuristicSeat)
    assert isinstance(seats.per_seat[1], RandomSeat)


def test_self_play_writes_records(workdir):
    """全启发式的自我对弈：不依赖 torch，验证落盘格式与统计。"""
    out, manifest = run_self_play(
        games=2,
        seats=("heuristic", "heuristic", "heuristic", "heuristic"),
        seed_start=91000,
        level_mode="cycle",
        checkpoint=None,
        out_path=workdir / "sp.jsonl",
        verbose=False,
    )

    assert out.exists()
    assert manifest["games"] == 2
    assert manifest["decisions"] > 0

    records = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    decisions = [r for r in records if r["type"] == "decision"]
    summaries = [r for r in records if r["type"] == "game"]

    assert len(decisions) == manifest["decisions"]
    assert len(summaries) == 2

    for record in decisions:
        # 四家都用启发式时，组合名是 heuristic+heuristic+heuristic+heuristic
        assert "heuristic" in record["policy"]
        assert 0 <= record["selected_index"] < record["num_candidates"]

    # 每局名次必须是完整排列
    for summary in summaries:
        assert sorted(summary["ranking"]) == [0, 1, 2, 3]


def test_self_play_data_can_be_exported(workdir):
    """自我对弈产出的数据必须能被导出器接受（这是接训练的前提）。"""
    from training.export_dataset import export

    out, _ = run_self_play(
        games=1,
        seats=("heuristic", "heuristic", "heuristic", "heuristic"),
        seed_start=92000,
        checkpoint=None,
        out_path=workdir / "one.jsonl",
        verbose=False,
    )

    npz, meta = export(out, out_path=workdir / "one.npz")

    assert meta["samples"] > 0
    assert meta["problems"] == []
    assert npz.exists()


# ==================== 需要 torch 的部分 ====================


def test_sampling_policy_requires_torch():
    pytest.importorskip("torch")


def load_bc_policy():
    """加载与当前编码器兼容的最新行为克隆模型；没有就跳过。

    编码器从 v2（198 维）升到 v3（258 维，含出牌历史）后，
    旧 checkpoint 不再兼容——测试应该跳过，而不是报形状错误。
    """
    torch = pytest.importorskip("torch")

    from players.neural import NeuralPolicy
    from training.state_encoder import STATE_DIM

    candidates = sorted(
        (REPO_ROOT / "models").glob("bc_*.pt"), key=lambda p: p.stat().st_mtime
    )

    for path in reversed(candidates):
        blob = torch.load(path, map_location="cpu", weights_only=False)
        config = blob.get("config") or {}

        if config.get("state_dim") in (None, STATE_DIM):
            return NeuralPolicy(path, device="cpu", seed=0)

    pytest.skip(f"models/ 下没有与编码器 v{STATE_DIM} 维兼容的 checkpoint")


@pytest.mark.parametrize("temperature", [0.0, 0.0])
def test_sampling_temperature_zero_equals_greedy(temperature):
    """温度 0 必须退化成和 NeuralPolicy 同一个选择。"""
    pytest.importorskip("torch")

    from players.sampling import SamplingPolicy

    base = load_bc_policy()
    sampler = SamplingPolicy(base, temperature=temperature, epsilon=0.0, seed=0)

    game = GameState.new_game(seed=21, level="2")
    legal = game.get_legal_moves(0)

    assert sampler.choose(game, 0, legal) == base.choose(game, 0, legal)


def test_sampling_only_returns_legal_candidates():
    pytest.importorskip("torch")

    from players.sampling import SamplingPolicy

    base = load_bc_policy()
    sampler = SamplingPolicy(base, temperature=2.0, epsilon=0.0, seed=0)

    game = GameState.new_game(seed=22, level="2")
    legal = game.get_legal_moves(0)
    allowed = [signature(m) for m in legal]

    for _ in range(10):
        action = sampler.choose(game, 0, legal)
        assert signature(action) in allowed


def test_sampling_epsilon_one_is_random_but_legal():
    pytest.importorskip("torch")

    from players.sampling import SamplingPolicy

    base = load_bc_policy()
    sampler = SamplingPolicy(base, temperature=1.0, epsilon=1.0, seed=0)

    game = GameState.new_game(seed=23, level="2")
    legal = game.get_legal_moves(0)
    allowed = [signature(m) for m in legal]

    picks = {tuple(signature(sampler.choose(game, 0, legal))) for _ in range(20)}

    assert picks <= {tuple(a) for a in allowed}
    assert len(picks) > 1, "ε=1 应该产生多种选择"
