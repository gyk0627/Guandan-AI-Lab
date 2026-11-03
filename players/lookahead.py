"""一步前瞻策略：用价值网络给「走完这一步之后的局面」打分。

思路（保守版）：

1. 先用行为克隆模型给所有候选动作打分，取出**最靠前的 K 个**；
2. 对这 K 个动作，逐个在引擎里真实模拟执行；
3. 用价值网络评估模拟后的局面（从「下一个行动者」的视角），换算出我方胜率；
4. 选我方胜率最高的那个动作。

为什么只在前 K 个里挑：行为克隆已经把明显糟糕的动作排除了，
价值网络（目前 AUC 约 0.63）只在「差不多好」的动作之间做裁决，
比让它对全部上千个候选做裁决更稳。

接口与其它策略一致：``choose(game, player, legal_moves)``。
"""

import copy
import random
from pathlib import Path

import numpy as np

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None

from game_engine.ranks import NORMAL_RANKS
from training.state_encoder import encode_action, encode_state


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class LookaheadPolicy:
    """行为克隆排序 + 价值网络裁决的一步前瞻策略。"""

    # 全局统计：用来确认「前瞻真的执行了」，而不是全部退回行为克隆
    total_decisions = 0
    total_lookaheads = 0
    total_fallbacks = 0
    total_overrides = 0

    def __init__(
        self,
        policy_checkpoint,
        value_checkpoint,
        top_k=5,
        device="auto",
        seed=None,
        name=None,
        max_candidates=60,
        min_value_gap=0.0,
    ):
        if torch is None:
            raise RuntimeError("LookaheadPolicy 需要 torch")

        from players.neural import NeuralPolicy
        from training.model import ValueNet

        self.device = pick_device(device)
        self.base = NeuralPolicy(policy_checkpoint, device=str(self.device), seed=seed)
        self.base.model.eval()

        blob = torch.load(
            Path(value_checkpoint), map_location=self.device, weights_only=False
        )
        self.value = ValueNet(**blob["config"]).to(self.device)
        self.value.load_state_dict(blob["model"])
        self.value.eval()

        self.top_k = int(top_k)
        self.max_candidates = int(max_candidates)
        # 只有价值差超过这个阈值，才推翻行为克隆的第一选择
        self.min_value_gap = float(min_value_gap)
        self.rng = random.Random(seed)
        self.name = name or (
            f"lookahead(top{self.top_k}, value_auc={blob.get('best_val_auc', 0):.3f})"
        )
        self.last_values = None
        # 候选太多时退回行为克隆，避免一次决策花掉 200ms
        self.fallbacks = 0

    # ---------------------------------------------------------------- 内部
    @torch.no_grad()
    def _score_candidates(self, game, player, candidates):
        level = getattr(game, "level", None)

        state = encode_state(game, player)
        vectors = np.asarray(
            [encode_action(candidate, level) for candidate in candidates],
            dtype=np.float32,
        )

        state_tensor = torch.from_numpy(np.asarray(state, dtype=np.float32)).unsqueeze(0)
        cand_tensor = torch.from_numpy(vectors).unsqueeze(0)
        mask = torch.ones((1, len(candidates)))

        scores, _ = self.base.model(
            state_tensor.to(self.device),
            cand_tensor.to(self.device),
            mask.to(self.device),
        )

        return scores.squeeze(0).cpu().numpy()

    @torch.no_grad()
    def _value_of_state(self, state):
        tensor = torch.from_numpy(np.asarray(state, dtype=np.float32)).unsqueeze(0)

        return float(torch.sigmoid(self.value(tensor.to(self.device))).item())

    def _our_win_probability(self, game, player, action):
        """模拟执行 action，返回「我方最终头游」的估计概率。"""
        sim = copy.deepcopy(game)

        if action is None:
            sim.pass_turn(player)
        else:
            sim.play(player, action)

        if sim.game_over:
            first_out = sim.finished_players[0]
            our_team = {player, (player + 2) % 4}

            return 1.0 if first_out in our_team else 0.0

        next_player = sim.current_player
        probability = self._value_of_state(encode_state(sim, next_player))

        if next_player == (player + 2) % 4:
            # 下一个是我的队友：他赢就是我赢
            return probability

        # 下一个是对手：他赢的概率，反过来说就是我赢的概率
        return 1.0 - probability

    # ---------------------------------------------------------------- 对外
    def choose(self, game, player, legal_moves):
        candidates = self.base.build_candidates(game, player, legal_moves)

        if not candidates:
            return None

        if len(candidates) == 1:
            return candidates[0]

        type(self).total_decisions += 1

        if len(candidates) > self.max_candidates:
            # 候选太多：编码本身就是瓶颈，直接交给行为克隆
            self.fallbacks += 1
            type(self).total_fallbacks += 1
            return self.base.choose(game, player, legal_moves)

        type(self).total_lookaheads += 1

        scores = self._score_candidates(game, player, candidates)

        if self.top_k < len(candidates):
            shortlist = list(np.argsort(scores)[::-1][: self.top_k])
        else:
            shortlist = list(range(len(candidates)))

        values = []

        for index in shortlist:
            values.append(self._our_win_probability(game, player, candidates[index]))

        self.last_values = values
        best_position = int(np.argmax(values))
        best = shortlist[best_position]

        # 保守模式：价值差不够大时，保持行为克隆的第一选择
        if self.min_value_gap > 0 and best_position != 0:
            if values[best_position] - values[0] < self.min_value_gap:
                type(self).total_overrides += 1
                return candidates[shortlist[0]]

        return candidates[best]
