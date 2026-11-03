"""带温度的采样策略：把「打分网络」变成「会探索的策略」。

为什么需要它：

* 自我对弈时，如果永远取 argmax，四家 AI 会反复走同一条线，产出大量重复对局；
* SDMC 论文里的「Soft Action Sampling」也是同一个思路——**在价值接近的动作之间采样**，
  而不是硬取最大值；
* 温度 T 控制探索强度：T→0 退化成 argmax，T 越大越随机。

另外保留 ε-greedy 作为兜底探索（按比例随机乱走一手），
用于打破自我对弈早期的局部循环。

接口与其它策略一致：``choose(game, player, legal_moves)`` → 牌列表 或 None（过牌）。
"""

import random

from game_engine.ranks import NORMAL_RANKS

try:  # torch 只在真正用到神经网络时才需要
    import torch
except ImportError:  # pragma: no cover - 没装 torch 的环境
    torch = None


class SamplingPolicy:
    """在基础策略的候选打分上按 softmax(score / T) 采样。"""

    def __init__(self, base, temperature=1.0, epsilon=0.0, seed=None, name=None):
        if torch is None:
            raise RuntimeError("SamplingPolicy 需要 torch；请先安装 PyTorch")

        if not hasattr(base, "model") or not hasattr(base, "build_candidates"):
            raise TypeError(
                "SamplingPolicy 需要一个 NeuralPolicy 作为基础策略"
                "（它要能给出候选列表与打分模型）"
            )

        self.base = base
        self.temperature = float(temperature)
        self.epsilon = float(epsilon)
        self.rng = random.Random(seed)
        self.name = name or f"sampling(T={self.temperature:g},eps={self.epsilon:g})"
        self.last_probabilities = None

    @torch.no_grad()
    def choose(self, game, player, legal_moves):
        candidates = self.base.build_candidates(game, player, legal_moves)

        if not candidates:
            return None

        # ε-greedy：偶尔完全随机，避免自我对弈陷入同一条线路
        if self.epsilon > 0 and self.rng.random() < self.epsilon:
            self.last_probabilities = None
            return self.rng.choice(candidates)

        level = getattr(game, "level", None)

        from training.state_encoder import encode_action, encode_state
        import numpy as np

        state = encode_state(game, player)
        vectors = np.asarray(
            [encode_action(candidate, level) for candidate in candidates],
            dtype=np.float32,
        )

        state_tensor = torch.from_numpy(
            np.asarray(state, dtype=np.float32)
        ).unsqueeze(0).to(self.base.device)
        cand_tensor = torch.from_numpy(vectors).unsqueeze(0).to(self.base.device)
        mask = torch.ones((1, len(candidates)), device=self.base.device)

        scores, _ = self.base.model(state_tensor, cand_tensor, mask)
        scores = scores.squeeze(0)

        if self.temperature <= 0:
            # 温度 0 = 纯贪心
            index = int(scores.argmax().item())
            self.last_probabilities = None
            return candidates[index]

        probabilities = torch.softmax(scores / self.temperature, dim=0)
        index = int(torch.multinomial(probabilities, 1).item())

        self.last_probabilities = probabilities.detach().cpu().numpy()
        return candidates[index]


class HeuristicSeat:
    """把启发式包成「座位策略」，接口与 SamplingPolicy 一致。"""

    def __init__(self, seed=None, name="heuristic"):
        self.rng = random.Random(seed)
        self.name = name

    def choose(self, game, player, legal_moves):
        from players.heuristic import choose_move

        return choose_move(
            game.hands[player],
            legal_moves,
            rng=self.rng,
            game_state=game,
            player=player,
        )


class RandomSeat:
    """随机策略座位。"""

    def __init__(self, seed=None, name="random"):
        self.rng = random.Random(seed)
        self.name = name

    def choose(self, game, player, legal_moves):
        return self.rng.choice(legal_moves) if legal_moves else None


class SeatPolicies:
    """按座位分派策略：同一局里四家可以用不同策略。"""

    def __init__(self, per_seat, name=None):
        missing = [seat for seat in range(4) if seat not in per_seat]

        if missing:
            raise ValueError(f"缺少座位策略：{missing}")

        self.per_seat = dict(per_seat)
        self.name = name or "+".join(
            self.per_seat[seat].name for seat in range(4)
        )

    def choose(self, game, player, legal_moves):
        return self.per_seat[player].choose(game, player, legal_moves)

    def describe(self):
        labels = {0: "你", 1: "下家", 2: "队友", 3: "上家"}

        return " | ".join(
            f"{labels[seat]}={self.per_seat[seat].name}" for seat in range(4)
        )
