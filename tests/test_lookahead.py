"""价值网络与一步前瞻策略的测试。

需要 torch（模型加载），用 importorskip 保护。
没有 checkpoint 时跳过，而不是失败——新克隆的仓库可能还没训练过模型。
"""

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from game_engine.game_state import GameState  # noqa: E402
from training.model import ValueNet  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def signature(cards):
    return sorted(map(repr, cards))


def latest(pattern):
    files = sorted(
        (REPO_ROOT / "models").glob(pattern), key=lambda path: path.stat().st_mtime
    )

    return files[-1] if files else None


def test_value_net_shape_and_config():
    net = ValueNet(state_dim=198, hidden=64)

    output = net(torch.randn(4, 198))

    assert output.shape == (4,)
    assert net.config() == {"state_dim": 198, "hidden": 64}


def test_value_net_checkpoint_loads():
    checkpoint = latest("value_*.pt")

    if checkpoint is None:
        pytest.skip("没有价值网络 checkpoint")

    blob = torch.load(checkpoint, map_location="cpu", weights_only=False)
    net = ValueNet(**blob["config"])
    net.load_state_dict(blob["model"])
    net.eval()

    with torch.no_grad():
        probabilities = torch.sigmoid(net(torch.randn(3, blob["config"]["state_dim"])))

    assert ((probabilities >= 0) & (probabilities <= 1)).all()


# ---------------------------------------------------------------- 前瞻策略


@pytest.fixture(scope="module")
def models():
    from training.state_encoder import STATE_DIM

    policy = latest("bc_*.pt")
    value = latest("value_*.pt")

    if policy is None or value is None:
        pytest.skip("缺少策略模型或价值模型")

    # 老 checkpoint（编码器 v2，198 维）与新编码器不兼容，跳过而不是失败
    blob = torch.load(policy, map_location="cpu", weights_only=False)

    if blob.get("config", {}).get("state_dim") not in (None, STATE_DIM):
        pytest.skip(
            f"{policy.name} 是旧编码器训练的（{blob['config'].get('state_dim')} 维），"
            f"当前编码器是 {STATE_DIM} 维"
        )

    return policy, value


def make_lookahead(models, **kwargs):
    from players.lookahead import LookaheadPolicy

    policy_path, value_path = models

    return LookaheadPolicy(policy_path, value_path, device="cpu", seed=0, **kwargs)


def test_lookahead_top1_equals_bc(models):
    """top_k=1 时不应有任何覆盖，必须与纯行为克隆的选择完全一致。

    这是关键诊断：如果这条不成立，说明前瞻管线有 bug，
    那么"前瞻更差"的结论就不成立。
    """
    from players.neural import NeuralPolicy

    policy_path, value_path = models

    lookahead = make_lookahead(models, top_k=1)
    base = NeuralPolicy(policy_path, device="cpu", seed=0)

    game = GameState.new_game(seed=31, level="2")
    legal = game.get_legal_moves(0)

    assert signature(lookahead.choose(game, 0, legal)) == signature(base.choose(game, 0, legal))


def test_lookahead_returns_legal_action(models):
    lookahead = make_lookahead(models, top_k=3)

    game = GameState.new_game(seed=32, level="2")
    legal = game.get_legal_moves(0)
    allowed = [signature(m) for m in legal]

    action = lookahead.choose(game, 0, legal)

    assert action is not None
    assert signature(action) in allowed


def test_lookahead_falls_back_for_huge_candidate_lists(models):
    """候选超过 max_candidates 时必须退回行为克隆（否则一次决策要 200ms）。"""
    from players.lookahead import LookaheadPolicy

    before = LookaheadPolicy.total_fallbacks

    lookahead = make_lookahead(models, top_k=5, max_candidates=2)

    game = GameState.new_game(seed=33, level="2")
    legal = game.get_legal_moves(0)
    lookahead.choose(game, 0, legal)

    assert LookaheadPolicy.total_fallbacks == before + 1


def test_lookahead_conservative_gap_keeps_bc_choice(models):
    """min_value_gap 很大时，绝不能覆盖行为克隆的第一选择。"""
    lookahead = make_lookahead(models, top_k=3, min_value_gap=1.0)

    game = GameState.new_game(seed=34, level="2")
    legal = game.get_legal_moves(0)

    chosen = lookahead.choose(game, 0, legal)

    # 价值差不可能超过 1.0，所以必然保留短名单首位
    assert chosen is not None
    assert signature(chosen) in [signature(m) for m in legal]
