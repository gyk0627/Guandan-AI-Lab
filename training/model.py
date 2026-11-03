"""候选动作打分网络。

结构（刻意保持简单，先要能训练、能验证、能比较）：

    状态向量 (198)  ->  MLP  ->  h (128)
    候选动作 (65)   ->  MLP  ->  c (128)
    score = MLP([h, c])          对每个候选动作打分
    value = MLP(h)               预测「本队是否头游」

训练目标是行为克隆：让正确动作的分数高于同批次其它合法动作（交叉熵 + mask）。

为什么是「候选打分」而不是「动作空间固定分类」：掼蛋每一步的合法动作数量
随局面剧烈变化（同一手牌领出可能有上千个候选），固定输出维度没法用。
"""

import torch
import torch.nn as nn

NEG_INF = -1e9


class CandidateScorer(nn.Module):
    """候选动作打分 + 价值预测。"""

    def __init__(
        self,
        state_dim,
        action_dim,
        hidden=256,
        cand_hidden=128,
        dropout=0.1,
    ):
        super().__init__()

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden = hidden
        self.cand_hidden = cand_hidden

        half = hidden // 2

        self.state_net = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, half),
            nn.ReLU(),
        )

        self.cand_net = nn.Sequential(
            nn.Linear(action_dim, cand_hidden),
            nn.ReLU(),
            nn.Linear(cand_hidden, cand_hidden),
            nn.ReLU(),
        )

        self.score_head = nn.Sequential(
            nn.Linear(half + cand_hidden, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

        self.value_head = nn.Sequential(
            nn.Linear(half, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, state, candidates, mask):
        """返回 (scores, value)。

        state:      (B, state_dim)
        candidates: (B, W, action_dim)
        mask:       (B, W)，1 表示真实候选

        scores 中被 mask 掉的位置是 -1e9，softmax 后概率为 0。
        """
        hidden = self.state_net(state)                       # (B, half)
        cand = self.cand_net(candidates)                     # (B, W, cand_hidden)

        width = cand.shape[1]
        hidden_expanded = hidden.unsqueeze(1).expand(-1, width, -1)

        joined = torch.cat([hidden_expanded, cand], dim=-1)
        scores = self.score_head(joined).squeeze(-1)         # (B, W)

        scores = scores.masked_fill(mask <= 0, NEG_INF)

        value = self.value_head(hidden).squeeze(-1)          # (B,)

        return scores, value

    # 便于保存 / 加载时重建结构
    def config(self):
        return {
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "hidden": self.hidden,
            "cand_hidden": self.cand_hidden,
        }


class ValueNet(nn.Module):
    """只做一件事：给局面打分——从这个局面出发，当前玩家所在队最终能否头游。

    与 CandidateScorer 里的 value_head 区别：
    * value_head 是训练策略时的辅助任务，输入是策略网络的隐含层；
    * ValueNet 是独立的评估器，只看状态向量，可以被「一步前瞻」反复调用。

    输出是 logit，训练用二元交叉熵，评估用 AUC。
    """

    def __init__(self, state_dim, hidden=256, dropout=0.1):
        super().__init__()

        self.state_dim = state_dim
        self.hidden = hidden
        self.dropout = dropout

        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, state):
        return self.net(state).squeeze(-1)

    def config(self):
        return {"state_dim": self.state_dim, "hidden": self.hidden}

