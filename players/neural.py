"""神经网络策略：把训练好的候选打分模型接进对局 / 评估。

接口与 evaluation/head_to_head.py 里其它策略一致：

    policy.choose(game, player, legal_moves) -> 牌列表 或 None（过牌）

注意：候选列表的构造必须和训练时**完全一致**——
先放全部合法出牌，最后再放「过牌」。顺序错了模型学到的下标就对不上。
"""

from pathlib import Path

import numpy as np
import torch

from game_engine.legal_moves import generate_candidates
from training.model import CandidateScorer
from training.state_encoder import encode_action, encode_state


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class NeuralPolicy:
    """候选打分策略。"""

    def __init__(self, checkpoint, device="auto", seed=None):
        checkpoint = Path(checkpoint)

        if not checkpoint.exists():
            raise FileNotFoundError(f"找不到模型：{checkpoint}")

        self.device = pick_device(device)

        blob = torch.load(checkpoint, map_location=self.device, weights_only=False)

        config = blob.get("config") or {}

        # 编码器版本校验：v2 = 198 维，v3 = 258 维（含出牌历史序列）。
        # 老 checkpoint 与新编码器混用只会得到一个形状错误堆栈，
        # 这里提前给出可操作的提示。
        from training.state_encoder import ENCODER_VERSION, STATE_DIM

        checkpoint_dim = config.get("state_dim")
        checkpoint_version = blob.get("encoder_version", 2)

        if checkpoint_dim is not None and checkpoint_dim != STATE_DIM:
            raise ValueError(
                f"模型 {checkpoint.name} 的状态维度是 {checkpoint_dim}"
                f"（编码器 v{checkpoint_version}），"
                f"而当前编码器是 v{ENCODER_VERSION}（{STATE_DIM} 维）。"
                f"请用当前数据重新训练："
                f"python -m training.train_bc（数据需先用 export_dataset 重新导出）"
            )

        self.model = CandidateScorer(**config).to(self.device)
        self.model.load_state_dict(blob["model"])
        self.model.eval()

        self.checkpoint = str(checkpoint)
        self.meta = {
            "trained_on": blob.get("trained_on"),
            "best_epoch": blob.get("best_epoch"),
            "best_val_acc": blob.get("best_val_acc"),
            "encoder_version": checkpoint_version,
        }

        # 接口要求带 seed 参数；这个策略本身是确定性的，保留是为了兼容工厂协议
        self.seed = seed

    def build_candidates(self, game, player, legal_moves):
        """与训练时一致的候选顺序：合法出牌 + 最后的过牌。"""
        candidates = list(legal_moves)

        if game.last_play is not None:
            candidates.append(None)

        return candidates

    @torch.no_grad()
    def choose(self, game, player, legal_moves):
        candidates = self.build_candidates(game, player, legal_moves)

        if not candidates:
            return None

        level = getattr(game, "level", None)

        state = encode_state(game, player)
        vectors = np.asarray(
            [encode_action(candidate, level) for candidate in candidates],
            dtype=np.float32,
        )

        state_tensor = torch.from_numpy(
            np.asarray(state, dtype=np.float32)
        ).unsqueeze(0).to(self.device)

        cand_tensor = torch.from_numpy(vectors).unsqueeze(0).to(self.device)
        mask = torch.ones((1, len(candidates)), device=self.device)

        scores, _ = self.model(state_tensor, cand_tensor, mask)
        index = int(scores.argmax(dim=1).item())

        return candidates[index]

    def describe(self):
        return (
            f"NeuralPolicy({Path(self.checkpoint).name}, "
            f"epoch={self.meta['best_epoch']}, "
            f"val_acc={self.meta['best_val_acc']})"
        )


def register(strategy_name="neural", checkpoint=None, device="auto"):
    """把神经网络策略注册进评估器的策略表。"""
    from evaluation import head_to_head

    if checkpoint is None:
        candidates = sorted(
            (Path(__file__).resolve().parent.parent / "models").glob("*.pt"),
            key=lambda path: path.stat().st_mtime,
        )

        if not candidates:
            raise FileNotFoundError("models/ 下没有 .pt，请先训练")

        checkpoint = candidates[-1]

    cache = {}

    def factory(seed):
        # 每个座位一个实例会重复占显存，这里共享同一个模型
        if "policy" not in cache:
            cache["policy"] = NeuralPolicy(checkpoint, device=device, seed=seed)

        return cache["policy"]

    head_to_head.STRATEGY_FACTORIES[strategy_name] = factory

    return checkpoint
