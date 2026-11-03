# GuanDan AI Lab 数据格式说明

> 本文基于 2026-11-02 的代码实测。字段表来自 `training/collect_data.py`、`training/check_dataset.py`、
> `training/export_dataset.py` 的源码；样例与规模数字来自 `training/data/games_20261102_212830.*`
> 的实际读取结果（`np.load` 与逐行 `json.loads`）。

数据管线一共两种落盘格式：

| 阶段 | 文件 | 谁写 | 谁读 | 用途 |
|---|---|---|---|---|
| 采集 | `training/data/games_<时间戳>.jsonl` | `training.collect_data.collect_dataset` | `training.check_dataset`（查结构）、`training.export_dataset`（重放） | 人类可读的原始对局记录 |
| 采集 | `training/data/games_<时间戳>.manifest.json` | 同上 | 人 | 这批数据是怎么采的（种子范围、策略、过牌数…） |
| 导出 | `training/data/games_<时间戳>.npz` | `training.export_dataset.export` | （将来的）训练脚本 | 定长 numpy 数组 |
| 导出 | `training/data/games_<时间戳>.meta.json` | 同上 | 人 / 训练脚本 | 维度、样本数、候选统计 |

---

## 1. 目录与命名约定

```text
training/data/
├── games_20261102_212830.jsonl           # 采集产物：UTF-8，一行一条 JSON，无 BOM
├── games_20261102_212830.manifest.json   # 采集清单（与 jsonl 同名）
├── games_20261102_212830.npz             # 导出产物（与 jsonl 同名）
└── games_20261102_212830.meta.json       # 导出元数据（与 npz 同名）
```

约定（都是代码里的实际行为）：

| 约定 | 说明 | 代码位置 |
|---|---|---|
| 时间戳格式 | `YYYYmmdd_HHMMSS`，来自 `datetime.now().strftime("%Y%m%d_%H%M%S")` | `collect_data.collect_dataset` |
| 同名配对 | manifest 用 `output_path.with_suffix(".manifest.json")`；npz/meta 用 `Path(path).with_suffix(".npz")` / `.with_suffix(".meta.json")` | 同上 / `export_dataset.export` |
| 「最新文件」 | 所有脚本省略路径参数时都取 `sorted(DATA_DIR.glob("games_*.jsonl"), key=mtime)[-1]` | `check_dataset.latest_file`、`export_dataset.main` |
| 只能有一个 `.jsonl` 后缀 | `.with_suffix` 会替换最后一个后缀，所以 `games_x.jsonl` → `games_x.manifest.json`（不是 `.jsonl.manifest.json`） | — |
| 行序 | 每局先若干行 `decision`，**最后一行**是该局的 `game` 摘要；局与局之间按 seed 顺序 | `collect_data.dump_game` |
| 排序 | 每行都 `json.dumps(..., ensure_ascii=False, sort_keys=True)`，**不写时间戳**（可复现的前提） | 同上 |

另有**调试日志**，格式完全不同（`event` 字段区分 `game_start`/`turn`/`game_end`，牌是 `["S","3"]` 数组而不是 `"S:3"`）：

```text
replay/game_<YYYYmmdd_HHMMSS>_<seed>.jsonl     # replay/game_logger.py::GameLogger
```

不要把 `replay/game_*.jsonl` 和 `training/data/games_*.jsonl` 混用，两者字段名都不一样。

---

## 2. 牌文本格式（**必须带冒号**）

内存里一张牌是 `("S","3")` 元组，大小王是裸字符串 `"SJ"` / `"BJ"`。落盘时统一由
`training/serialize.py` 转成文本：

| 内存 | 落盘文本 | 说明 |
|---|---|---|
| `("S","3")` | `"S:3"` | 花色:点数 |
| `("H","10")` | `"H:10"` | 点数 `10` 是两位，照原样写 |
| `("D","A")` | `"D:A"` | — |
| `("S","J")` | `"S:J"` | **黑桃 J** |
| `"SJ"` | `"SJ"` | 小王 |
| `"BJ"` | `"BJ"` | 大王 |

**这是真实踩过的坑**：如果为了省事写成 `"S3"` 这种拼接形式，`("S","J")` 会变成 `"SJ"`，
和小王撞车 —— 重放时黑桃 J 被解析成小王，整局手牌全部错位，而且**不会报错**。

现在代码里做了硬防护：

```text
text_to_card("S3")  → ValueError: 无法解析的牌：S3（普通牌必须写成 S:3 这种带冒号的形式）
text_to_card("XJ")  → ValueError: 无法解析的牌：XJ
text_to_card("S")   → ValueError: 无法解析的牌：S
```

反过来，`card_to_text("S3")` 也会抛 `ValueError: 无法识别的王：S3`（裸字符串只允许 `"SJ"`/`"BJ"`）。

对应测试：`tests/test_data_pipeline.py::test_spade_jack_does_not_collide_with_small_joker`
（断言 `card_to_text(("S","J")) != card_to_text("SJ")`，且两者各自 round-trip 正确）。

---

## 3. `decision` 记录：逐字段表

一条 `decision` = **一个决策时刻**。字段顺序按 `sort_keys` 排列，方便 diff。

| 字段 | 类型 | 含义 | 示例 |
|---|---|---|---|
| `type` | `str` | 记录类型，恒为 `"decision"` | `"decision"` |
| `game` | `str` | 对局 id，格式 `s<seed>-L<level或none>` | `"s5000-L2"` |
| `seed` | `int` | 发牌种子（同 seed + 同 level 可完整重放） | `5000` |
| `level` | `str \| null` | 本局级牌；`null` = 无级牌模式 | `"2"` |
| `policy` | `str` | 采集时用的策略：`"heuristic"` / `"random"` | `"heuristic"` |
| `turn` | `int` | 第几步（1 起，等于该局内的行动序号） | `1` |
| `player` | `int` | 行动玩家 `0..3`（0/2 = A 队，1/3 = B 队） | `0` |
| `team` | `str` | `player` 所属队伍，`"A"` / `"B"` | `"A"` |
| `hand` | `list[str]` | **该玩家此刻的全部手牌**（文本牌，顺序 = 引擎内部顺序） | `["C:Q","C:A","SJ", …]` |
| `last_play` | `list[str] \| null` | 桌面上一手牌；`null` = 本步是领出 | `null` |
| `last_player` | `int \| null` | 上一手出牌者；`null` = 无人领出 | `null` |
| `pass_count` | `int` | 当前连续过牌数（清桌后归 0） | `0` |
| `finished` | `list[int]` | 已出完的玩家，按出完先后 | `[]` |
| `hand_counts` | `list[int]` | 四家剩余张数，**按绝对座位 0/1/2/3 排列** | `[27,27,27,27]` |
| `num_candidates` | `int` | 候选动作总数，**≥1**，「过牌」算一个候选 | `219` |
| `selected_index` | `int` | 实际动作在候选列表里的下标，`0 <= x < num_candidates` | `73` |
| `action` | `list[str] \| null` | 实际打出的牌；`null` = 过牌 | `["H:8","D:9","H:10","C:J","D:Q"]` |
| `action_type` | `str` | `"play"` 或 `"pass"`，与 `action` 必须自洽 | `"play"` |

候选列表的顺序（决定 `selected_index` 的含义，**改了这个顺序旧数据全部作废**）：

1. `GameState.get_legal_moves(player)` 返回的合法出牌，保持引擎生成顺序；
2. 如果 `last_play is not None`，**最后追加一个 `None` 代表过牌**；
3. 如果 `last_play is None`（领出），没有过牌这一项。

因此 `num_candidates == 1` 且 `action_type == "pass"` 的唯一合法情形是「队友是上一手出牌者」。

---

## 4. `game` 记录：逐字段表

一局恰好一条，紧跟在该局所有 `decision` 之后。

| 字段 | 类型 | 含义 | 示例 |
|---|---|---|---|
| `type` | `str` | 恒为 `"game"` | `"game"` |
| `game` | `str` | 对局 id，与 decision 对应 | `"s5299-L2"` |
| `seed` | `int` | 发牌种子 | `5299` |
| `level` | `str \| null` | 本局级牌 | `"2"` |
| `policy` | `str` | 采集策略 | `"heuristic"` |
| `steps` | `int` | 总行动次数，**必须等于该局 decision 条数** | `94` |
| `ranking` | `list[int]` | 完整名次，`ranking[0]` = 头游；必须是 `[0,1,2,3]` 的一个排列 | `[3,0,1,2]` |
| `first_out_team` | `str` | 率先出完者的队伍，`"A"`/`"B"` | `"B"` |
| `team_rank` | `dict[str,int]` | 两队各自的最佳名次（1..4），只能取 `{1,2}` 或 `{1,3}` 两种组合 | `{"A":2,"B":1}` |
| `level_up` | `dict[str,int]` | 两队各升几级：第一&第二升 3、第一&第三升 2、第一&第四升 1、没进前二 0 | `{"A":0,"B":2}` |

> `team_rank` 的两种合法形态来自 `check_dataset.check_file` 的断言 `team_ranks in ([1,2],[1,3])`：
> 赢家队伍包了前两名（**双下**）→ `{1,2}`；否则对方有一个人插在第二 → `{1,3}`。

---

## 5. 真实样例

### 5.1 `decision`（`games_20261102_212830.jsonl` 第 1 行）

> 文件里这是**一整行**；下面为便于阅读做了缩进，并把 `hand` 截断到 5 张（**已截断**，
> 原文是完整 27 张）。除 `hand` 外每个字段都是原文。

```json
{
  "type": "decision",
  "game": "s5000-L2",
  "seed": 5000,
  "level": "2",
  "policy": "heuristic",
  "turn": 1,
  "player": 0,
  "team": "A",
  "hand": ["C:Q", "C:A", "SJ", "H:10", "D:4"],
  "last_play": null,
  "last_player": null,
  "pass_count": 0,
  "finished": [],
  "hand_counts": [27, 27, 27, 27],
  "num_candidates": 219,
  "selected_index": 73,
  "action": ["H:8", "D:9", "H:10", "C:J", "D:Q"],
  "action_type": "play"
}
```

读法：第 1 步玩家 0（A 队）领出（`last_play` 为 `null`），手牌 27 张；
引擎认为有 219 个候选，策略选了下标 73 的「8-9-10-J-Q 顺子」（不含 2，所以是普通顺子而非同花顺）。

### 5.2 `decision`（同文件第 2 行，注意 `last_play` 与 `hand_counts`）

```json
{
  "type": "decision",
  "game": "s5000-L2",
  "seed": 5000,
  "level": "2",
  "policy": "heuristic",
  "turn": 2,
  "player": 1,
  "team": "B",
  "hand": ["S:9", "S:3", "H:Q", "C:5", "D:6"],
  "last_play": ["H:8", "D:9", "H:10", "C:J", "D:Q"],
  "last_player": 0,
  "pass_count": 0,
  "finished": [],
  "hand_counts": [22, 27, 27, 27],
  "num_candidates": 38,
  "selected_index": 29,
  "action": ["C:10", "C:J", "S:Q", "H:K", "H:A"],
  "action_type": "play"
}
```

两个值得注意的点：

- `hand_counts[0] == 22`：上一手打了 5 张，**四家张数是按绝对座位 0/1/2/3 排的**，不是相对当前玩家。
- 上家是玩家 0，与玩家 1 **不是队友**（队友是 3），所以可以压；若上家是玩家 3，则 `num_candidates` 会是 `1` 且 `action_type` 为 `"pass"`。

### 5.3 `game`（同文件最后一行，**原文逐字**）

```json
{"first_out_team": "B", "game": "s5299-L2", "level": "2", "level_up": {"A": 0, "B": 2}, "policy": "heuristic", "ranking": [3, 0, 1, 2], "seed": 5299, "steps": 94, "team_rank": {"A": 2, "B": 1}, "type": "game"}
```

读法：玩家 3（B 队）头游，接着 0（A）、1（B）、2（A）；B 队最佳名次 1、A 队 2 → B 队升 2 级。

---

## 6. `.npz`：每个数组的 shape / dtype / 含义

实测读取结果（`np.load("training/data/games_20261102_212830.npz")`）：

| 数组 | shape | dtype | 含义 |
|---|---|---|---|
| `states` | `(27794, 198)` | `float32` | 每条样本的**状态**向量（`encode_state`，见 [ARCHITECTURE.md](ARCHITECTURE.md) §5.4）。全部在 [0,1] |
| `cand_flat` | `(645088, 65)` | `float32` | **所有样本的所有候选动作**，按样本顺序首尾相接展平；每行是一个 `encode_action` |
| `cand_offsets` | `(27795,)` | `int32` | 长度 = 样本数 + 1。样本 `i` 的候选是 `cand_flat[offsets[i]:offsets[i+1]]`；`offsets[0]` 恒为 0，`offsets[-1] == cand_flat.shape[0]` |
| `y_index` | `(27794,)` | `int32` | 正确动作在该样本候选区间内的**相对下标**（0 起），即 JSONL 里的 `selected_index` |
| `hand_ranks` | `(27794,)` | `int8` | 该样本玩家最终名次 `1..4`（`ranking.index(player)+1`） |
| `team_win` | `(27794,)` | `int8` | 该样本**所在队伍**是否率先出完（1/0）。**按每条记录自己的 `team` 算**，不是全局一个值 |
| `level_up` | `(27794,)` | `int8` | 该样本所在队伍升几级：`0/1/2/3` |
| `is_pass` | `(27794,)` | `int8` | 正确动作是否过牌（1/0） |

一致性约束（实测校验过）：

```text
cand_offsets 差分之和 == cand_flat 行数 == 645088
cand_offsets 差分最小值 >= 1                # 每条样本至少 1 个候选
0 <= y_index[i] < offsets[i+1] - offsets[i]
```

`cand_offsets` 是**变长候选**的关键：不做补边也能训练（按样本切片），这正是这份数据只有 4.67 MB 的原因。

---

## 7. `.meta.json` 字段说明

实测原文（`games_20261102_212830.meta.json`）：

| 字段 | 类型 | 含义 | 本数据集的值 |
|---|---|---|---|
| `source` | `str` | 来源 JSONL 文件名 | `"games_20261102_212830.jsonl"` |
| `samples` | `int` | 样本数（= decision 行数） | `27794` |
| `games` | `int` | 成功重放并导出的对局数 | `300` |
| `state_dim` | `int` | 状态维度 | `198` |
| `action_dim` | `int` | 动作维度 | `65` |
| `avg_candidates` | `float` | 平均候选数（`总候选/样本数`，两位小数） | `23.21` |
| `max_candidates` | `int` | 单样本最大候选数（**补边时的峰值**） | `1635` |
| `pass_ratio` | `float` | 过牌比例（四位小数） | `0.5754` |
| `rank_distribution` | `dict[str,int]` | 名次 1..4 各多少样本 | `{"1":5825,"2":6888,"3":7633,"4":7448}` |
| `team_win_ratio` | `float` | `team_win` 的均值 | `0.4776` |
| `level_up_distribution` | `dict[str,int]` | 升 0/1/2/3 级各多少样本 | `{"0":14520,"1":3653,"2":6594,"3":3027}` |
| `problems` | `list[str]` | 重放阶段发现的问题；**空列表才表示干净** | `[]` |

`problems` 非空说明某局「重放后对局没结束」或缺结束记录 —— 这类样本不会被静默丢掉，而是记在这里。

---

## 8. `.manifest.json` 字段说明

| 字段 | 含义 | 本数据集的值 |
|---|---|---|
| `file` | jsonl 文件名 | `"games_20261102_212830.jsonl"` |
| `created` | 采集时间（ISO，秒精度） | `"2026-11-02T21:29:22"` |
| `num_games` | 局数 | `300` |
| `start_seed` | 起始种子 | `5000` |
| `level_mode` | 级牌模式 `cycle`/`fixed`/`none` | `"cycle"` |
| `fixed_level` | `fixed` 模式下的级牌 | `null` |
| `policy` | 采集策略 | `"heuristic"` |
| `decisions` | 决策样本数 | `27794` |
| `actions` | `{"pass": n, "play": n}` | `{"pass":15994,"play":11800}` |
| `first_out_team` | 头游队伍分布 | `{"A":152,"B":148}` |
| `avg_steps` | 平均行动次数（两位小数） | `92.65` |

注意 `level_mode` 是 `cycle` 时，级牌按 `NORMAL_RANKS[index % 13]` 轮转（`2,3,…,A,2,…`），
所以 `level` 字段在一批数据里是**混的**；同一 `seed` 配不同 `level` 是完全不同的牌局。

---

## 9. 已知规模（实测，`training/data/games_20261102_212830.*`）

| 指标 | 数值 | 来源 |
|---|---|---|
| 对局数 | 300 | `.manifest.json` `num_games` |
| 决策样本数 | 27,794 | `.manifest.json` `decisions` / `.meta.json` `samples` |
| 总候选数 | 645,088 | `cand_flat.shape[0]` |
| 平均候选 | 23.21 | `.meta.json` `avg_candidates` |
| 最大候选 | 1,635 | `.meta.json` `max_candidates` |
| 过牌率 | 57.54%（15,994 / 27,794） | `.meta.json` `pass_ratio`、`.manifest.json` `actions` |
| 状态维度 | 198 | `states.shape[1]` |
| 动作维度 | 65 | `cand_flat.shape[1]` |
| `games_*.jsonl` 体积 | 12,279,635 B ≈ **11.71 MB** | 文件系统 |
| `games_*.npz` 体积 | 4,892,540 B ≈ **4.67 MB** | 文件系统（`savez_compressed`） |
| `cand_flat` 未压缩体积 | 645,088 × 65 × 4 B ≈ **160 MiB** | 计算值 |
| 平均步数 | 92.65 | `.manifest.json` `avg_steps` |

---

## 10. 补边警告：**不要全局按最大候选宽度补边**

`cand_flat` 是变长的（候选数从 1 到 1635）。很多模型实现图省事会直接
`(样本数, 全局最大候选数, 65)` 一次补齐 —— 在本数据集上这是灾难：

```text
27794 样本 × 1635（全局最大候选） × 65（动作维度） × 4 B（float32）
= 11,815,229,400 B ≈ 11.0 GiB      ← 单是这一个张量
```

而实际数据只占 160 MiB（压缩后 4.67 MB），**浪费 98% 以上**，而且绝大多数行都是 0。

正确做法二选一：

1. **按 batch 内实际最大宽度补边**（推荐）：`training/export_dataset.py::pad_candidates`
   支持显式 `max_width`，传入本批 `np.diff(cand_offsets[i:j]).max()`：

   ```python
   from training.export_dataset import pad_candidates
   import numpy as np

   start, end = 0, 512                      # 本 batch 的样本区间 [start, end)
   offsets = cand_offsets[start:end + 1]    # 长度 = 本批样本数 + 1
   width = int(np.diff(offsets).max())      # 本批实际最大候选数

   padded, mask = pad_candidates(
       cand_flat[offsets[0]:offsets[-1]],
       offsets - offsets[0],                # pad_candidates 内部按 0 起算，必须先归零
       max_width=width,
   )
   # padded: (end - start, width, 65) float32 ; mask: (end - start, width) float32
   ```

   实测（本数据集前 512 条样本）：`width = 856`、`padded.shape = (512, 856, 65)`、
   `mask.sum() == 14,334`（`== offsets 差分之和`，逐行核对一致）、占用 **108.7 MiB**。
   同样 512 条样本若按全局最大宽度 1635 补边，则是 512 × 1635 × 65 × 4 B ≈ **207.8 MiB**，几乎翻倍。

   注意 `pad_candidates` 的 `cand_offsets` 参数用的是**这批数据自己的偏移**（起点为 0），
   所以要先按 `batch_offsets[0]` 切 `cand_flat`。

2. **按候选数分桶**：把候选数相近的样本放一个 batch（例如 `1-8 / 9-32 / 33-128 / 129+`），
   桶内再取最大值补边。分桶能让 `mask` 的填充率保持在低位。

两个函数的差别（容易混）：

| | `training/export_dataset.pad_candidates(cand_flat, cand_offsets, max_width=None)` | `training.state_encoder.pad_candidates(vectors, dim=None)` |
|---|---|---|
| 输入 | 展平的大矩阵 + 偏移数组 | 一个样本的若干向量（元素可为 `None`） |
| 输出 mask | `float32` | `int`（0/1） |
| `max_width`/`dim` 缺省 | 取**整份数据**的最大候选数（就是上面那个 1635，危险） | 取**本批**所有真实向量的最大长度 |
| 典型用途 | 导出后组 batch | 推理时给一手候选补齐 |

---

## 11. 校验数据的两条命令（定位不同）

```powershell
# ① 只查结构：不导入引擎，27,794 行实测 0.28 秒，适合采完立刻扫一遍
$env:PYTHONIOENCODING='utf-8'; & .\.venv\Scripts\python.exe -m training.check_dataset

# ② 重放 + 语义校验：慢（要真跑一遍对局），但能抓出规则漂移
$env:PYTHONIOENCODING='utf-8'; & .\.venv\Scripts\python.exe -m training.export_dataset
```

`check_dataset` 会检查（`REQUIRED_DECISION_FIELDS` 17 个 + `REQUIRED_GAME_FIELDS` 9 个必填）：

- 字段齐全、JSON 合法、记录类型只允许 `decision`/`game`；
- 一局内 `seed`/`level`/`policy` 与结束记录一致；
- `ranking` 是 `0..3` 的排列、`steps` 等于 decision 条数、`team_rank` 与实际名次对得上；
- `0 <= selected_index < num_candidates`、`num_candidates >= 1`；
- `action_type` 与 `action` 自洽（过牌必须 `action is null`，且 `last_play` 不能是 `null`）；
- `sum(hand_counts) <= 108`、`len(hand) == hand_counts[player]`。

`export_dataset` 会**重放整局**，任何一条不满足就抛 `RuntimeError`：当前玩家不符、手牌不符、
**候选数量不符**、`selected_index` 越界、候选与动作不符、对局没结束。
这就是「规则改了但旧数据没重导」会被发现的地方。

两条命令都省略路径参数时自动取最新文件；也可以显式传路径：`-m training.check_dataset path\to.jsonl`。

---

## 12. 兼容性红线

| 红线 | 违反后果 | 代码里的拦截 |
|---|---|---|
| 牌文本必须带冒号 | 黑桃 J 与小王撞车，手牌错位 | `serialize.text_to_card` 抛 `ValueError` |
| 旧格式（记录里自带 `state` 字段）不再支持 | 编码器已换 v2（198/65），旧向量无意义 | `export_dataset.load_records` 抛 `ValueError("…旧数据已作废，请用 training.collect_data 重新采集。")` |
| 候选顺序（合法出牌在前、过牌在最后）不可改 | 旧数据的 `selected_index` 全部错位 | 由 `export` 的候选数量/动作校验兜住 |
| `PATTERN_TYPES` 顺序不可改 | 牌型 one-hot 全错位 | `state_encoder.PATTERN_TYPES` 直接引用它，注释写明「顺序固定，不要随意调整」 |
| `STATE_SEGMENTS` / `ACTION_SEGMENTS` 顺序与长度不可改 | 198/65 维语义全变，旧 npz 失效 | `test_encoder.py::test_dimensions_are_stable` 逐段钉死 |
