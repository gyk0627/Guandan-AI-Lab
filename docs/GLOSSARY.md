# GuanDan AI Lab 术语表

> 本文基于 2026-11-02 的代码实测。每个术语后面都给了**代码里对应的符号**，
> 中文名来自 `patterns.TYPE_LABELS`（打印用），英文 id 来自 `patterns.TYPE_*` 常量（**权威**）。

**这份表存在的唯一理由**：旧 README 把「三带二」叫成「飞机带对」，把「三张」和「飞机」混着用，
导致讨论规则时三个人说的不是一回事。以后一律以**英文 id** 为准，中文名只用来对话。

---

## 1. 九种牌型

牌型 id 就是**代码里的字符串常量**，直接写在数据文件、日志、编码器里，改它等于改数据格式。

| 英文 id | 中文名 | 英文名（建议说法） | 一句话定义 | 张数 |
|---|---|---|---|---|
| `single` | 单张 | single | 任意一张牌 | 1 |
| `pair` | 对子 | pair | 两张**同点数**的牌（两副牌里同点数最多 4 张，所以对子很好凑） | 2 |
| `triple` | 三张 | three of a kind | 三张同点数 | 3 |
| `triple_pair` | 三带二 | full house（三张带一对） | **一组**三张 + **一组**对子，只有这一种形态 | 5 |
| `straight` | 顺子 | straight | 恰好 5 张**连续**点数，至少两种花色；可含 2（只能当最小）；**不含大小王**；`A2345` 不算 | 5 |
| `flush_straight` | 同花顺 | straight flush | 5 张**同花色**的连续点数（= 同花色的顺子），属于**炸弹类** | 5 |
| `pair_chain` | 连对 | consecutive pairs / tractor | **≥2 组连续**的对子，可含 2，不含王；互压时张数必须相同 | 4、6、8、…、26（2~13 对） |
| `plane` | 连续飞机 | consecutive triples | **≥2 组连续**的三张，不含王；**不允许带对子** | 6、9、12、…、27（2~9 组） |
| `bomb` | 炸弹 | bomb | 4~8 张**同点数**；**四王炸不存在**；8 张最大 | 4、5、6、7、8 |

补充规则（都在代码与测试里）：

- **顺子恰好 5 张，一共只有 9 种**：`23456 / 34567 / … / 10JQKA`。`A2345` 不算（2 在最低端，A 与 2 不相邻）。
- **连对/连续飞机可以含 2**，但 2 只能当最小的那一端（`2233` 合法，`AA22` 不连续）。
- **「飞机带对」在本项目不存在**：`3334445566` 非法（`test_invalid_patterns` 明确断言）。
- **炸弹阶梯**（`compare.bomb_power` 的实测值）：
  `4 炸(40) < 同花顺(45) < 5 炸(50) < 6 炸(60) < 7 炸(70) < 8 炸(80)`；
  同张数炸弹比点数；炸弹类可以压任何普通牌型。
- **一手牌只有一个解释**：能同时解释成多种牌型时，按 `TYPE_PRIORITY` 取最高
  （炸弹 > 同花顺 > 连续飞机 > 连对 > 顺子 > 三带二 > 三张 > 对子 > 单张）。
  例：`33355` 只会被认成 `triple_pair`（三带二），不会认成「飞机带对」。
- **主牌（`main_rank`）怎么取**：
  | 牌型 | 比什么 |
  |---|---|
  | `single` / `pair` / `triple` / `bomb` | 就是那个点数 |
  | `triple_pair` | **只看三张**，对子不参与比较（`33322` 与 `333AA` 平手） |
  | `straight` / `flush_straight` / `pair_chain` / `plane` | 窗口里**最大**的那个点数 |

---

## 2. 常用术语

| 术语 | 英文 | 含义 | 代码里在哪 | 状态 |
|---|---|---|---|---|
| **级牌** | level card | 本局「打几」的那个点数。牌力临时上浮到 **15**（高于 A=14，低于小王=16）。打 2 时，单张 2 能压 A，但压不过小王 | 参数名 `level`；`ranks.LEVEL_VALUE = 15`；`ranks.rank_value(rank, level)` | ✅ 已实现 |
| **逢人配** | wildcard（红桃级牌） | **花色为红桃、点数等于级牌**的那张牌，可以当**除大小王之外的任意一张牌**（点数、花色都可变）。单独出时按级牌本身算（单张，牌力 15） | `wildcards.is_wildcard(card, level)`；`split_wildcards`；`WILDCARD_SUIT = "H"` | ✅ 已实现（D1.5） |
| **头游** | first out | 第一个把手上 27 张打完的人。**头游所在队伍获胜**（本项目唯一胜负口径） | `game.finished_players[0]`；`collect_data.team_of(...)`；`summary["first_out_team"]` | ✅ 已实现 |
| **双下** | double down / 1-2 finish | 同一队包揽前两名（名次 1 和 2）。数据里体现为 `team_rank == {"A":1,"B":2}` 或反之 | 无专门字段；`check_dataset` 断言 `sorted(team_rank.values()) in ([1,2],[1,3])` | ✅ 可识别（没有单独的布尔字段） |
| **接风** | — | 领出者出完牌后，由谁接替领出 | 只有临时实现：`pass_turn` 里「`leader` 已出完就顺延给下一个未出完的人」，注释标注**待按纸质规则确认** | ⚠️ 部分实现 / 待确认 |
| **进贡** | tribute | 上一局输家把最大的牌交给赢家 | 全仓无对应代码 | ❌ **未实现** |
| **抗贡** | resist tribute | 输家手上有两张大王时可以拒绝进贡 | 全仓无对应代码 | ❌ **未实现** |
| **领出 / 自由出牌** | leading | 当前没有桌面牌（`last_play is None`），必须出牌、**不能过** | `GameState.last_play is None`；`pass_turn` 抛 `"领出阶段不能过牌"` | ✅ 已实现 |
| **过牌 / 不要** | pass | 不出牌，跳过本轮。只在有桌面牌时允许 | `GameState.pass_turn`；`encode_action(None)`；`is_pass` 标签 | ✅ 已实现 |
| **一轮 / 清桌** | trick | 其余人全部过牌后，桌面清空、牌权重回最后出牌的人 | `pass_turn` 里 `pass_count >= required_passes` 分支 | ✅ 已实现 |
| **牌权** | control | 谁在领出。`leader` 字段 | `GameState.leader` | ✅ 已实现 |
| **名次** | ranking | 四人出完的先后顺序，`[头游, 二游, 三游, 末游]` | `GameState.finished_players`；`summary["ranking"]`；npz 的 `hand_ranks` | ✅ 已实现 |
| **升级** | level up | 按名次换算升几级：第一&第二升 3、第一&第三升 2、第一&第四升 1 | `collect_data.upgrade_amount`；npz 的 `level_up` | ⚠️ **只作为数据标签**，引擎没有升级赛流程 |
| **候选** | candidate | 某个决策时刻所有可选的出牌（+ 可选的「过牌」），有固定顺序：合法出牌在前、过牌最后 | `generate_candidates`；`num_candidates` / `selected_index` | ✅ 已实现 |
| **牌堆** | deck | 两副牌 = 2 × (4 花色 × 13 点数 + 小王 + 大王) = **108 张**，四人各 27 张 | `cards.create_deck()` | ✅ 已实现 |

---

## 3. 代码符号 ↔ 概念对照

接手时最容易迷路的是「概念叫什么」和「代码里叫什么」对不上。这张表按概念分组。

### 3.1 牌力与点数

| 代码符号 | 在哪 | 对应概念 | 实测/约定值 |
|---|---|---|---|
| `level` | 到处（`GameState.level`、函数参数） | 级牌（本局打几） | `"2".."A"` 或 `None`；`None` = 无级牌模式 |
| `NORMAL_RANKS` | `ranks.py` | 13 个普通点数，按**牌力升序** | `("2","3",…,"K","A")` |
| `NORMAL_VALUE` | `ranks.py` | 自然牌力 | `2→2, 3→3, …, A→14` |
| `LEVEL_VALUE` | `ranks.py` | 级牌上浮后的牌力 | `15` |
| `JOKER_VALUE` | `ranks.py` | 王的牌力 | `SJ→16, BJ→17` |
| `rank_value(rank, level)` | `ranks.py` | 「这张牌多大」的唯一函数 | 级牌→15，其余自然值 |
| `natural_value(rank)` | `ranks.py` | 「不考虑级牌时多大」 | 2..14 / 16 / 17 |
| `windows(length)` / `STRAIGHT_WINDOWS` | `ranks.py` | 连续窗口；9 种顺子 | `len(STRAIGHT_WINDOWS) == 9` |
| `WILDCARD_SUIT` / `WILDCARD_RANKS` | `wildcards.py` | 逢人配的花色 / 能变成的点数 | `"H"` / 全部 13 个普通点数 |

### 3.2 牌型

| 代码符号 | 在哪 | 对应概念 | 备注 |
|---|---|---|---|
| `TYPE_SINGLE`…`TYPE_BOMB` | `patterns.py` | 9 个牌型 id 常量 | **就是落盘字符串**，不要改名 |
| `PATTERN_TYPES` | `patterns.py` | 9 种牌型的**固定顺序**元组 | 编码器按它铺 one-hot；改顺序 = 旧数据全废 |
| `TYPE_PRIORITY` | `patterns.py` | 多解时的取舍优先级 | 炸弹 9 > 同花顺 8 > 飞机 7 > 连对 6 > 顺子 5 > 三带二 4 > 三张 3 > 对子 2 > 单张 1 |
| `TYPE_LABELS` | `patterns.py` | id → 中文名 | 只用于显示/日志 |
| `type_label(info)` | `patterns.py` | 取中文名；`None` → `"不合法"` | — |
| `is_bomb_like(info)` | `patterns.py` | 「是不是炸弹类」 | 炸弹 + 同花顺 |
| `analyze_cards(cards, level=None)` | `patterns.py` | 「这是什么牌型」 | 判不出 → `None`；漏传 `level` 会把含逢人配的牌判成 `None` |
| `BOMB_MIN` / `BOMB_MAX` | `patterns.py`、`compare.py` | 炸弹张数范围 | `4` / `8` |
| `FLUSH_STRAIGHT_POWER` | `compare.py` | 同花顺在炸弹阶梯里的强度 | `45` |

### 3.3 出牌与候选

| 代码符号 | 在哪 | 对应概念 | 备注 |
|---|---|---|---|
| `generate_candidates(hand, level=None)` | `legal_moves.py` | 「这手牌能打出哪些牌组合」 | **不含过牌**；按组合去重；顺序与手牌传入顺序无关 |
| `legal_moves(hand, previous, level)` | `legal_moves.py` | 「能压过 `previous` 的牌」 | **不处理队友**、不校验是否轮到你 |
| `GameState.get_legal_moves(player)` | `game_state.py` | 对局中唯一该用的「我能出什么」 | 会挡「不能压队友」/已结束/没轮到你；返回 `[]` 有两种含义 |
| `EXHAUSTIVE_PATTERNS` / `CANONICAL_PATTERNS` | `legal_moves.py` | 两类生成模板 | 前者枚举花色选法，后者（连对/飞机）只取一个规范解 |
| `can_beat(candidate, previous, level)` | `compare.py` | 「能不能压过」 | 非法牌型抛 `ValueError` |
| `compare_cards(a, b, level)` | `compare.py` | 「谁大」→ `1/0/-1` | `0` 也可能是「异型不能互压」 |

### 3.4 编码与数据集

| 代码符号 | 在哪 | 对应概念 | 实测值 |
|---|---|---|---|
| `STATE_DIM` / `STATE_SEGMENTS` | `state_encoder.py` | 状态向量维度与分段 | `198`（12 段） |
| `ACTION_DIM` / `ACTION_SEGMENTS` | `state_encoder.py` | 动作向量维度与分段 | `65`（4 段：牌 54 / 牌型 9 / 张数 1 / 过牌 1） |
| `RELATIVE_ORDER` | `state_encoder.py` | 相对座位顺序 | `(1,2,3,0)` = 左家/对家/右家/自己 |
| `CARD_DIM` / `PATTERN_DIM` | `state_encoder.py` | 牌面 54 维 / 牌型 9 维 | `4×13 + 2 = 54`；`9` |
| `encode_state` / `encode_action` | `state_encoder.py` | 状态 / 动作编码 | — |
| `MAX_HAND = 27` | `state_encoder.py` | 归一化用的手牌上限 | `27` |
| `num_candidates` / `selected_index` | JSONL | 候选数 / 实际动作下标 | 顺序：合法出牌在前，过牌最后 |
| `hand_ranks` / `team_win` / `level_up` / `is_pass` | npz | 四个标签数组 | 见 [DATA_FORMAT.md](DATA_FORMAT.md) §6 |
| `first_out_team` / `team_rank` / `ranking` | JSONL | 头游队伍 / 队伍最佳名次 / 完整名次 | — |

### 3.5 一个不存在的符号：`WORST`

任务书/旧笔记里提到过 `WORST`（「最差分数」的哨兵常量）。**实测全仓 grep 无任何匹配，
这个符号不存在。** 真正起「最差」作用的是两个写死的小数值：

| 表达式 | 值 | 含义 | 位置 |
|---|---|---|---|
| `move_cost(...)` 判不出牌型时 | `1000.0` | 「这手牌型非法，别选」 | `players/heuristic.py` |
| `evaluate_move(...)` 选中的牌不在手里时 | `10000.0` | 「这手牌根本打不出去」 | 同上 |
| `hand_cost(...)` | 无哨兵 | 分数**越低越好**，没有上界 | 同上 |

要引用「最差分」，请说「`move_cost` 的 1000 惩罚」或「`evaluate_move` 的 10000 惩罚」，
不要说 `WORST` —— 代码里没有这个东西。

---

## 4. 历史遗留的术语混乱（这张表就是为了以后不再混）

旧 README（已经重写）在第六节牌型表里把「三带二」写成了「**飞机带对**」，
并说 `33355` 要按「飞机带对」处理。这直接污染了后续所有讨论：同一手 `33355`，
一个人说「飞机带对」，另一个人说「三带二」，第三个人以为在说 `333444`。

订正记录在 `CHANGELOG.md` 第 199 行（「旧 README 与代码不符清单」第 6 条），
术语提醒在 `docs/RULES.md` 第 158 行。**现在统一按下表：**

| 旧叫法（错/易混） | 现在的正确说法 | 代码里的 id | 一句话区分 |
|---|---|---|---|
| 「飞机带对」 | **三带二** | `triple_pair` | 三张 + 一对，共 5 张，只有一种形态 |
| 「飞机」被用来指**三张** | **三张** | `triple` | 三张同点数，3 张 |
| 「飞机」被用来指 `333444` | **连续飞机**（≥2 组连续三张） | `plane` | 至少 6 张、且点数连续 |
| 「飞机带单/带对/带翅膀」 | **不存在这种牌型** | — | `33344455`、`3334445566` 全部非法 |
| 「连对」说成「拖拉机」「木板」 | **连对** | `pair_chain` | ≥2 组连续对子，张数相同才能互压 |
| 「同花顺」说成「钢化」「火箭」 | **同花顺** | `flush_straight` | 同花色顺子，属炸弹类 |
| 「王炸」「四王炸」 | **不存在** | — | `SJ SJ BJ BJ` 非法；两个小王只是 `pair`（对子） |

> 说明证据等级：仓库里能逐字查到的旧说法只有「飞机带对」那一条（`CHANGELOG.md` 第 199 行）。
> 「三张被叫成飞机」「拖拉机」这类说法来自口头讨论与更早的版本，原始出处已被重写覆盖、
> **无法逐字引用**。但这三种混淆在讨论里反复出现，所以照样列出来当对照表用。

顺带记两个**不是术语、但同一批遗留错误**的规则订正（都在 `CHANGELOG.md` 的清单里）：

| 旧 README 说法 | 代码实际 | 出处 |
|---|---|---|
| 点数顺序「3,4,5,…,A,2」，即 **2 最大** | **2 最小**：`2 < 3 < … < A < 级牌 < 小王 < 大王` | `CHANGELOG.md` 第 195 行（#2） |
| 状态 58 维 / 动作 25 维 / 牌型 9 维 | **198 / 65 / 9** | `CHANGELOG.md` 第 194 行（#1） |

---

## 5. 一句话速查（贴墙上）

```text
2 最小，A 最大，级牌夹在 A 和小王之间（15）。
红桃级牌叫逢人配，能当除王以外的任何牌。
三张叫 triple，三带二叫 triple_pair，连续三张才叫 plane（飞机）。
飞机不带对子。四王炸不存在。8 张炸弹最大。
一手牌只有一个解释，取优先级最高的那种。
队友的牌不能压；领出不能过；过牌也是候选之一（放最后）。
分析牌型永远要带 level —— 少传一个参数，逢人配就会「消失」。
```
