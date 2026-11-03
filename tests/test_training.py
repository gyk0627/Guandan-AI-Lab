"""训练链路测试：数据集切分、批次补边、模型、训练一步、模型加载。

这些测试需要 torch。没有装 torch 的环境会自动跳过，不会让规则测试变红。
"""

import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from training.dataset import (  # noqa: E402
    batch_stats,
    candidate_lengths,
    collate,
    load_dataset,
    make_batches,
    split_by_game,
)
from training.model import CandidateScorer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir():
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def make_synthetic(path, games=4, samples_per_game=5, state_dim=8, action_dim=4):
    """造一个小数据集，候选数量各不相同。"""
    states = []
    flat = []
    groups_flat = []
    offsets = [0]
    y_index = []
    team_win = []
    game_index = []

    rng = np.random.default_rng(0)

    for game in range(games):
        for sample in range(samples_per_game):
            width = 3 + (sample % 4)

            states.append(rng.random(state_dim).astype(np.float32))
            flat.append(rng.random((width, action_dim)).astype(np.float32))
            # 每两个候选算同一组，模拟「同手牌不同花色」
            groups_flat.append(np.arange(width, dtype=np.int16) // 2)
            offsets.append(offsets[-1] + width)
            y_index.append(int(sample % width))
            team_win.append(1 if game % 2 == 0 else 0)
            game_index.append(game)

    np.savez_compressed(
        path,
        states=np.asarray(states, dtype=np.float32),
        cand_flat=np.asarray(np.concatenate(flat), dtype=np.float32),
        cand_groups=np.asarray(np.concatenate(groups_flat), dtype=np.int16),
        cand_offsets=np.asarray(offsets, dtype=np.int32),
        y_index=np.asarray(y_index, dtype=np.int32),
        team_win=np.asarray(team_win, dtype=np.int8),
        hand_ranks=np.ones(len(states), dtype=np.int8),
        level_up=np.zeros(len(states), dtype=np.int8),
        is_pass=np.zeros(len(states), dtype=np.int8),
        game_index=np.asarray(game_index, dtype=np.int32),
    )

    return path


def test_split_by_game_keeps_games_whole(workdir):
    path = make_synthetic(workdir / "toy.npz", games=10, samples_per_game=4)
    data = load_dataset(path)

    train, val = split_by_game(data["game_index"], val_fraction=0.2, seed=0)

    assert len(train) + len(val) == len(data["game_index"])

    train_games = set(data["game_index"][train].tolist())
    val_games = set(data["game_index"][val].tolist())

    assert not (train_games & val_games), "同一局不能同时进训练集和验证集"
    assert len(val_games) == 2


def test_candidate_lengths_and_batches(workdir):
    path = make_synthetic(workdir / "toy.npz")
    data = load_dataset(path)

    lengths = candidate_lengths(data["cand_offsets"])
    # 每局 5 条样本，候选数按 sample % 4 循环：3,4,5,6,3
    assert lengths.tolist() == [3, 4, 5, 6, 3] * 4

    batches = make_batches(np.arange(20), lengths, batch_size=8, shuffle=False)
    assert sum(len(batch) for batch in batches) == 20

    # 不打乱时，同一批里的候选数量应该尽量接近
    first = lengths[batches[0]]
    assert first.max() - first.min() <= 3


def test_collate_shapes_and_mask(workdir):
    path = make_synthetic(workdir / "toy.npz")
    data = load_dataset(path)

    states, cands, mask, labels, values, groups = collate([0, 1, 2, 3], data)

    assert states.shape == (4, 8)
    assert cands.shape == (4, 6, 4)     # 本批最大候选 6
    assert mask.shape == (4, 6)
    assert labels.shape == (4,)
    assert values.shape == (4,)
    assert groups is not None and groups.shape == (4, 6)

    # 每行的 mask 之和等于该样本真实的候选数
    assert mask.sum(dim=1).tolist() == [3.0, 4.0, 5.0, 6.0]

    # 补边位置的组号是 -1
    assert groups[0, 3:].tolist() == [-1, -1, -1]


def test_batch_stats(workdir):
    path = make_synthetic(workdir / "toy.npz")
    data = load_dataset(path)

    stats = batch_stats(data)

    assert stats["samples"] == 20
    assert stats["max"] == 6
    assert 3 <= stats["avg"] <= 6


def test_model_shapes_and_masking():
    model = CandidateScorer(state_dim=8, action_dim=4, hidden=16, cand_hidden=8, dropout=0.0)
    model.eval()

    states = torch.randn(5, 8)
    cands = torch.randn(5, 7, 4)
    mask = torch.ones(5, 7)
    mask[:, 4:] = 0                      # 后 3 个是 padding

    scores, value = model(states, cands, mask)

    assert scores.shape == (5, 7)
    assert value.shape == (5,)

    # padding 位置的分数必须是负无穷级别，softmax 后概率为 0
    assert torch.all(scores[:, 4:] < -1e8)

    probs = torch.softmax(scores, dim=1)
    assert torch.allclose(probs[:, 4:], torch.zeros(5, 3), atol=1e-6)
    assert torch.allclose(probs.sum(dim=1), torch.ones(5), atol=1e-6)


def test_one_training_step_reduces_loss(workdir):
    path = make_synthetic(workdir / "toy.npz", games=6, samples_per_game=8)
    data = load_dataset(path)

    torch.manual_seed(0)
    model = CandidateScorer(state_dim=8, action_dim=4, hidden=16, cand_hidden=8, dropout=0.0)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-2)

    batch = np.arange(24)
    losses = []

    for _ in range(12):
        states, cands, mask, labels, _, _ = collate(batch, data)

        scores, _ = model(states, cands, mask)
        loss = torch.nn.functional.cross_entropy(scores, labels)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        losses.append(loss.item())

    assert losses[-1] < losses[0], "训练若干步后 loss 应该下降"


def test_checkpoint_roundtrip(workdir):
    model = CandidateScorer(state_dim=8, action_dim=4, hidden=16, cand_hidden=8, dropout=0.0)

    path = workdir / "ckpt.pt"
    torch.save(
        {"model": model.state_dict(), "config": model.config()},
        path,
    )

    blob = torch.load(path, map_location="cpu", weights_only=False)
    restored = CandidateScorer(**blob["config"])
    restored.load_state_dict(blob["model"])

    params_a = [p.detach().clone() for p in model.parameters()]
    params_b = [p.detach().clone() for p in restored.parameters()]

    assert all(torch.equal(a, b) for a, b in zip(params_a, params_b))


def test_neural_policy_returns_legal_action(workdir):
    """随机权重的策略也必须返回「合法动作」或「过牌」，不能瞎给。"""
    from game_engine.game_state import GameState
    from players.neural import NeuralPolicy
    from training.state_encoder import ACTION_DIM, STATE_DIM

    model = CandidateScorer(state_dim=STATE_DIM, action_dim=ACTION_DIM, hidden=32, cand_hidden=16)
    path = workdir / "random.pt"

    torch.save(
        {
            "model": model.state_dict(),
            "config": model.config(),
            "trained_on": "random",
            "best_epoch": 0,
            "best_val_acc": 0.0,
        },
        path,
    )

    policy = NeuralPolicy(path, device="cpu", seed=0)

    game = GameState.new_game(seed=7, level="2")
    legal = game.get_legal_moves(0)

    chosen = policy.choose(game, 0, legal)

    assert chosen is None or chosen in legal

    # 走一步，确认引擎接受
    if chosen is not None:
        game.play(0, chosen)
    else:
        game.pass_turn(0)


def test_registered_strategy_is_usable():
    from evaluation import head_to_head
    from players import neural

    if not list((REPO_ROOT / "models").glob("*.pt")):
        pytest.skip("models/ 下还没有训练好的模型，先跑 training.train_bc")

    checkpoint = neural.register("neural_test")

    assert "neural_test" in head_to_head.STRATEGY_FACTORIES
    assert Path(checkpoint).exists()

    head_to_head.STRATEGY_FACTORIES.pop("neural_test", None)


# ==================== 置换等价（cand_groups） ====================


def test_equivalence_key_groups_suit_permutations():
    """同一副牌的顺子，只换花色，应该落到同一个等价组。"""
    from training.export_dataset import equivalence_key

    a = [("S", "3"), ("H", "4"), ("S", "5"), ("H", "6"), ("S", "7")]
    b = [("H", "3"), ("S", "4"), ("H", "5"), ("S", "6"), ("H", "7")]

    assert equivalence_key(a) == equivalence_key(b)


def test_equivalence_key_separates_ranks():
    from training.export_dataset import equivalence_key

    a = [("S", "3"), ("H", "4"), ("S", "5"), ("H", "6"), ("S", "7")]
    b = [("S", "4"), ("H", "5"), ("S", "6"), ("H", "7"), ("S", "8")]

    assert equivalence_key(a) != equivalence_key(b)


def test_equivalence_key_separates_flush_from_straight():
    """同花顺是炸弹，绝不能和普通顺子合并成一组。"""
    from training.export_dataset import equivalence_key

    straight = [("S", "3"), ("H", "4"), ("S", "5"), ("H", "6"), ("S", "7")]
    flush = [("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7")]

    assert equivalence_key(straight) != equivalence_key(flush)


def test_equivalence_key_separates_wildcard_usage():
    """打 2 时，红桃 2 是逢人配：打出它和打出普通 2 代价不同，不能合并。"""
    from training.export_dataset import equivalence_key

    wildcard = [("H", "2")]
    plain = [("S", "2")]

    assert equivalence_key(wildcard, level="2") != equivalence_key(plain, level="2")


def test_equivalence_key_pass_is_its_own_group():
    from training.export_dataset import equivalence_key

    assert equivalence_key(None) == equivalence_key([])
    assert equivalence_key(None) != equivalence_key([("S", "3")])


def test_group_candidates_assigns_compact_ids():
    from training.export_dataset import group_candidates

    candidates = [
        [("S", "3")],                       # 单张 3
        [("H", "3")],                       # 单张 3（不同花色）-> 同组
        [("S", "4")],                       # 单张 4 -> 新组
        None,                               # 过牌 -> 新组
    ]

    groups = group_candidates(candidates)

    assert groups[0] == groups[1]
    assert groups[0] != groups[2]
    assert groups[3] not in groups[:3]
    assert len(groups) == 4


def test_group_loss_accepts_any_member():
    """概率质量落在同一组里任何一个成员上，损失都一样。"""
    from training.train_bc import group_policy_loss

    scores = torch.tensor([[5.0, 4.0, 0.0]])
    groups = torch.tensor([[0, 0, 1]])
    mask = torch.ones(1, 3)

    loss_a, member = group_policy_loss(scores, torch.tensor([0]), groups, mask)
    loss_b, _ = group_policy_loss(scores, torch.tensor([1]), groups, mask)

    assert member.tolist() == [[True, True, False]]
    assert torch.allclose(loss_a, loss_b, atol=1e-6)

    log_prob = torch.log_softmax(scores, dim=1)
    expected = -(torch.logsumexp(log_prob[0, :2], dim=0))

    assert torch.allclose(loss_a, expected, atol=1e-5)


def test_group_loss_is_easier_than_exact_ce():
    """模型把概率放在同组的另一个成员上时，组损失应低于精确交叉熵。"""
    from training.train_bc import group_policy_loss

    scores = torch.tensor([[3.0, 2.5, 0.0]])
    groups = torch.tensor([[0, 0, 1]])
    mask = torch.ones(1, 3)
    labels = torch.tensor([0])

    group_loss, _ = group_policy_loss(scores, labels, groups, mask)
    exact_loss = torch.nn.functional.cross_entropy(scores, labels)

    assert group_loss.item() < exact_loss.item()


def test_group_loss_falls_back_without_groups():
    from training.train_bc import group_policy_loss

    scores = torch.randn(3, 5)
    labels = torch.tensor([1, 2, 0])
    mask = torch.ones(3, 5)

    loss, member = group_policy_loss(scores, labels, None, mask)

    assert torch.isfinite(loss)
    assert member.shape == (3, 1)


# ==================== 数据集合并 ====================


def test_merge_datasets_offsets_and_games(workdir):
    from training.merge_datasets import merge

    a = make_synthetic(workdir / "a.npz", games=3, samples_per_game=4)
    b = make_synthetic(workdir / "b.npz", games=2, samples_per_game=4)

    out, meta = merge([a, b], out_path=workdir / "merged.npz")
    data = np.load(out)

    da = np.load(a)
    db = np.load(b)

    assert data["states"].shape[0] == da["states"].shape[0] + db["states"].shape[0]
    assert data["cand_flat"].shape[0] == (
        da["cand_flat"].shape[0] + db["cand_flat"].shape[0]
    )
    assert data["cand_offsets"][-1] == data["cand_flat"].shape[0]
    assert np.all(np.diff(data["cand_offsets"]) >= 1)

    # 局号不能撞车
    assert data["game_index"].max() == meta["games"] - 1
    assert len(np.unique(data["game_index"])) == 5

    # 等价组号原样保留
    assert "cand_groups" in data.files


def test_merge_single_file_is_identity(workdir):
    from training.merge_datasets import merge

    a = make_synthetic(workdir / "a.npz", games=2, samples_per_game=3)
    out, _ = merge([a], out_path=workdir / "one.npz")
    data = np.load(out)

    assert data["states"].shape[0] == 6
    assert data["cand_offsets"][-1] == data["cand_flat"].shape[0]
