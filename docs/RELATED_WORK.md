# 相关工作（RELATED WORK）

> 用途：论文「相关工作」一节的文献底稿。
>
> **定位**：本文属于「**不完全信息博弈 + 强化学习**」；核心方法是**软深度蒙特卡洛（Soft-DMC）** + **人类反馈强化学习（RLHF）做策略校准**。**掼蛋只是基准环境，不是研究卖点**——本文不追求棋力 SOTA，也不把工作包装成"做出一个能打的掼蛋程序"。
>
> **本文要论证的两件事**：① 在不完全信息 + 2v2 合作 + 长视野的设定下，硬 DMC 的**硬回报价值目标方差大、噪声高**，需要**软目标与软采样**；② 纯自对弈得到的策略与**人类偏好不一致**，需要 **RLHF 校准**。
>
> **已有实证（路线选择的依据）**：行为克隆对启发式老师 **51.50%**；价值网络 **AUC 0.635**（v2 状态）；一步前瞻为**负结果（26.00%）**；状态表示加入出牌历史后 **AUC 0.70**，但前瞻进一步降到 **16.50%**；`top_k=1` 对照组逐局复现 51.50%，排除实现缺陷。
>
> **收录规则**：每条格式为「**标题**（作者，年份，会议/期刊）— [链接](URL)。一句话内容 + **与本文（Soft-DMC / RLHF 校准）的关联**」。只写能核实的真实链接；找不到就写「未找到可靠来源」+ 检索词，不猜、不补。
>
> 检索日期：2026-11-03。核对方式：`web_search` 检索 + Crossref（期刊/会议 DOI）+ DataCite（arXiv DOI）+ NeurIPS / PMLR / AAAI 官方论文页元数据核对。

---

## 一、PIMC 与深度蒙特卡洛树搜索

> PIMC（Perfect Information Monte Carlo）的做法是：把不完美信息博弈的当前信息集**确定化（determinization）**成若干个完美信息世界，在每个世界里搜索，再对根动作聚合。它有两类已知的结构性缺陷：**strategy fusion**（同一信息集内不同世界给出互相矛盾的决策，却被当成一个策略使用）与 **non-locality**（子博弈的价值评估受信息集之外的策略影响）。这两类缺陷是 PIMC 失效分析的主线，也是本文选择"不做确定化搜索、改从价值目标入手"的背景。

### 1.1 PIMC 的原始工作与牌类实践

- **Understanding the Success of Perfect Information Monte Carlo Sampling in Game Tree Search**（Long、Sturtevant、Buro、Furtak，2010，AAAI 2010）— [DOI:10.1609/aaai.v24i1.7562](https://doi.org/10.1609/aaai.v24i1.7562)。用合成博弈树识别决定 PIMC 强弱的博弈性质，并证明这些性质可在真实牌类中检测，从而解释"理论上有缺陷、实践上却常有效"的现象。**与本文（Soft-DMC / RLHF 校准）的关联**：这是 PIMC 失效分析的原点；本文的负结果与之互补——PIMC 的缺陷在信息集结构层，而我们的失效在价值目标与度量层，因此本文不修补搜索结构，而是提出软化价值目标与软采样。
- **GIB: Imperfect Information in a Computationally Challenging Game**（Ginsberg，2001，Journal of Artificial Intelligence Research 14:303–358）— [DOI:10.1613/jair.820](https://doi.org/10.1613/jair.820)。桥牌系统 GIB 把蒙特卡洛模拟与不完美信息推理结合，在桥牌上达到专家级水平，是牌类 PIMC 实践的代表作。**与本文（Soft-DMC / RLHF 校准）的关联**：它证明"确定化 + 模拟"在强信息约束的牌类中可用；本文沿用"用模拟回报学价值"的思路，但指出在 2v2 合作、长局高方差的掼蛋里，硬回报目标会让这种价值估计噪声过大。
- **Improving Search with Supervised Learning in Trick-Based Card Games**（Solinas、Rebstock、Buro，2019，AAAI 2019）— [DOI:10.1609/aaai.v33i01.33011158](https://doi.org/10.1609/aaai.v33i01.33011158)。在 Skat 上用深度网络预测各张牌的位置，改善 PIMC 的状态采样分布，显著提升牌力。**与本文（Soft-DMC / RLHF 校准）的关联**：它把学习信号用在"采样分布"而非价值目标上；Soft-DMC 则把"软化"放在价值目标与动作采样上，两者是同一问题的不同着力点，可并列作为"学习如何进入搜索"的两条路线。
- **Perfect Information Monte Carlo with Postponing Reasoning**（Arjonilla、Saffidine、Cazenave，2024，IEEE Conference on Games 2024）— [DOI:10.1109/CoG60054.2024.10645574](https://doi.org/10.1109/CoG60054.2024.10645574)。针对 PIMC 的 strategy fusion 提出推迟推理（postponing reasoning），在预算耗尽后用不产生策略融合的算法求解子博弈。**与本文（Soft-DMC / RLHF 校准）的关联**：说明 strategy fusion 必须在搜索或信息集层修补；本文承认这一点，但把研究问题换到"价值目标是否有能力支撑决策"，用 AUC 0.70 反而更差的负结果为"软化目标"提供独立论据。
- **Information Set Monte Carlo Tree Search**（Cowling 等，2012，IEEE Transactions on Computational Intelligence and AI in Games 4(2):120–143）— [DOI:10.1109/TCIAIG.2012.2200894](https://doi.org/10.1109/TCIAIG.2012.2200894)。用信息集节点替代逐个确定化的世界，在节点内按世界采样，从结构上规避 strategy fusion 与 non-locality。**与本文（Soft-DMC / RLHF 校准）的关联**：这是不完美信息搜索的正统修补路线；本文只做一步前瞻而不建树，负结果说明"即使不引入确定化，弱价值目标仍会让前瞻注入噪声"，从而把问题定位到价值学习而非搜索结构。

### 1.2 搜索-学习融合：从 AlphaGo 到 Student of Games

> 这一支把搜索当作策略/价值目标的**改进算子**：搜索产生的更优动作分布与胜负信号反过来训练网络。其共同前提是"搜索给出的目标足够可靠"；本文的负结果正是这个前提在合作型不完全信息博弈中不成立的反例。

- **Mastering the game of Go with deep neural networks and tree search**（Silver 等，2016，Nature 529:484–489）— [DOI:10.1038/nature16961](https://doi.org/10.1038/nature16961)。AlphaGo 用策略网络、价值网络与 MCTS 结合，击败李世石。**与本文（Soft-DMC / RLHF 校准）的关联**：本文的"策略网络 + 价值网络 + 前瞻"是这套组合的极简版；差别在于我们用 198/258 维手工特征、只做一步前瞻，且价值网络明显偏弱。
- **Mastering the game of Go without human knowledge**（Silver 等，2017，Nature 550:354–359）— [DOI:10.1038/nature24270](https://doi.org/10.1038/nature24270)。AlphaGo Zero 不用人类棋谱，纯自对弈 + MCTS 超越 AlphaGo。**与本文（Soft-DMC / RLHF 校准）的关联**：说明自对弈能突破人类数据上限，但它的搜索能提供高质量目标；本文尚未有自对弈 RL 闭环，BC 的天花板就是启发式老师（51.50% 对老师胜率即证据），这正是转向 DMC/Soft-DMC 的动机。
- **A general reinforcement learning algorithm that masters chess, shogi, and Go through self-play**（Silver 等，2018，Science 362:1140–1144）— [DOI:10.1126/science.aar6404](https://doi.org/10.1126/science.aar6404)。AlphaZero 用统一的自对弈算法在三个完美信息棋类上超越人类与专用程序。**与本文（Soft-DMC / RLHF 校准）的关联**：它的有效性建立在"MCTS 能给出可靠策略/价值目标"之上；本文的单步前瞻既无 rollouts 也无可靠价值，不能直接类比，这也解释了为什么 26.00% 的负结果不是"搜索无用"，而是"硬价值目标不足以支撑搜索"。
- **Mastering Atari, Go, chess and shogi by planning with a learned model**（Schrittwieser 等，2020，Nature 588:604–609）— [DOI:10.1038/s41586-020-03051-4](https://doi.org/10.1038/s41586-020-03051-4)。MuZero 学习隐式环境模型并在其上规划，在 Atari 与棋类上同时达到强水平。**与本文（Soft-DMC / RLHF 校准）的关联**：若要做多步搜索，MuZero 式"学一个可推演模型"是方向；本文有显式规则引擎但每次模拟需深拷贝局面，搜索成本高，因此短期路线是软化价值目标而不是加深搜索。
- **Combining Deep Reinforcement Learning and Search for Imperfect-Information Games**（Brown 等，2020，NeurIPS 2020）— [NeurIPS 2020 论文页](https://proceedings.neurips.cc/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html)。ReBeL 把 CFR 式搜索与深度强化学习结合，在不完美信息博弈上用学习出的价值函数做子博弈求解。**与本文（Soft-DMC / RLHF 校准）的关联**：不完美信息下的搜索需要反事实价值；本文的价值网络只预测"我方头游概率"，没有反事实基线，因此 ReBeL 式搜索不能直接套用，而这也说明价值目标本身需要重新设计。
- **Student of Games: A unified learning algorithm for both perfect and imperfect information games**（Schmid 等，2023，Science Advances 9）— [DOI:10.1126/sciadv.adg3256](https://doi.org/10.1126/sciadv.adg3256)。把搜索与学习统一到一个算法框架，在围棋、国际象棋、扑克等博弈上验证。**与本文（Soft-DMC / RLHF 校准）的关联**：说明"通用搜索 + 学习"可行，但依赖可微的博弈建模与大规模训练；本文在掼蛋上只做单步前瞻、价值网络偏弱，恰好暴露了通用框架在小算力合作博弈上的薄弱环节。

### 1.3 不完全信息搜索的另一主线：CFR 与子博弈求解

- **Regret Minimization in Games with Incomplete Information**（Zinkevich 等，2007，NIPS 2007）— [Semantic Scholar 论文页](https://www.semanticscholar.org/paper/Regret-Minimization-in-Games-with-Incomplete-Zinkevich-Johanson/db20a76a702be3ad4e7cebf7eeb7f1898827cebd)。提出反事实后悔最小化（CFR），在两人零和不完美信息博弈中收敛到纳什均衡。**与本文（Soft-DMC / RLHF 校准）的关联**：这是不完美信息搜索的理论基座；但掼蛋是 4 人两队合作、非零和，CFR 的收敛保证不能直接照搬，因此本文走的是"价值学习 + 偏好校准"而非博弈论求解。
- **Deep Counterfactual Regret Minimization**（Brown 等，2019，ICML 2019）— [arXiv:1811.00164](https://arxiv.org/abs/1811.00164)。用神经网络近似 CFR 的价值与策略，在扑克类基准上验证。**与本文（Soft-DMC / RLHF 校准）的关联**：若未来做掼蛋多步搜索，Deep CFR 比"单步价值裁决"更合适；本文当前的手工特征与 5000 局数据不足以支撑这种近似，这也是把问题收敛到"价值目标"层面的原因。
- **DeepStack: Expert-level artificial intelligence in heads-up no-limit poker**（Moravčík 等，2017，Science 356:508–513）— [DOI:10.1126/science.aam6960](https://doi.org/10.1126/science.aam6960)。用深度反事实价值网络 + 持续重解（continual re-solving）在单挑无限注德州扑克达到专家水平。**与本文（Soft-DMC / RLHF 校准）的关联**：它证明"搜索 + 学出来的价值函数"可行，前提是价值足够准；本文的 E11 是反面证据——全局 AUC 从 0.635 升到 0.700，前瞻胜率反而从 26.00% 掉到 16.50%，说明"更准"不等于"可用于决策"。
- **Superhuman AI for heads-up no-limit poker: Libratus beats top professionals**（Brown & Sandholm，2018，Science 359:418–424）— [DOI:10.1126/science.aao1733](https://doi.org/10.1126/science.aao1733)。用 CFR + 子博弈求解在单挑无限注德州扑克击败顶尖职业选手。**与本文（Soft-DMC / RLHF 校准）的关联**：不完美信息下的强搜索依赖博弈论解与反事实价值；掼蛋的 2v2 合作与让牌结构使两人零和的保证失效，本文因此不把 CFR 作为主路线。
- **Superhuman AI for multiplayer poker**（Brown & Sandholm，2019，Science 365:885–890）— [DOI:10.1126/science.aay2400](https://doi.org/10.1126/science.aay2400)。Pluribus 在 6 人无限注德州扑克上击败精英人类。**与本文（Soft-DMC / RLHF 校准）的关联**：多人不完美信息也可被攻破，但 Pluribus 的玩家各自为战、没有固定队友与队伍目标，与掼蛋的 2v2 合作/让牌结构不同，这使团队信用分配成为本文基准环境的额外难点。

---

## 二、Deep Monte-Carlo（DMC）

> DMC 通常指「深度网络 + 蒙特卡洛回报回归」的范式（DouZero 将其系统化并命名），用整局回报作为动作价值目标、由自对弈产生数据。它的优点是目标无偏、实现简单；代价是**回报方差大**，在长局、合作、稀疏奖励的博弈里尤其明显——这正是本文提出 Soft-DMC 的出发点。

### 2.1 DMC 的代表工作

- **DouZero: Mastering DouDizhu with Self-Play Deep Reinforcement Learning**（Zha 等，2021，ICML 2021）— [arXiv:2106.06135](https://arxiv.org/abs/2106.06135)。把深度蒙特卡洛（DMC）与动作编码、并行 actor 结合，从零自对弈数天即登顶 Botzone（344 个智能体），是 DMC 在斗地主上的代表。**与本文（Soft-DMC / RLHF 校准）的关联**：本文的候选打分网络与动作编码属于同一范式，但 DouZero 用**硬回报的 DMC** 更新策略；Soft-DMC 要把这个硬目标换成软目标/分布化目标，并用软采样替代 argmax，二者构成直接的方法对照。
- **DanZero: Mastering GuanDan Game with Reinforcement Learning**（Lu 等，2023，IEEE Conference on Games 2023）— [DOI:10.1109/CoG57401.2023.10333179](https://doi.org/10.1109/CoG57401.2023.10333179)。早期掼蛋强化学习系统：分布式 actor 自对弈采样 + DMC learner，160 CPU + 1 GPU 训练 30 天，报告超过 8 个启发式基线并达到人类水平。**与本文（Soft-DMC / RLHF 校准）的关联**：同一基准、同样的"复杂动作空间 + 长局高方差"困难；它走大算力硬 DMC，本文走单机小规模的方法分析与负结果，正好互补——它证明该基准可被强 RL 攻克，本文则说明硬目标在弱价值网络下会如何失效。
- **DanZero+: Dominating the GuanDan Game Through Reinforcement Learning**（Zhao 等，2024，IEEE Transactions on Games 16:914–926）— [DOI:10.1109/TG.2024.3422396](https://doi.org/10.1109/TG.2024.3422396)。DanZero 的期刊扩展版，用更系统的训练与搜索技巧把掼蛋强化学习推到压制级表现。**与本文（Soft-DMC / RLHF 校准）的关联**：它说明掼蛋本身可被大算力 RL 攻克，反衬出本文的负结果只在"BC + 弱价值 + 单步前瞻"这一受限设定下成立；同时它没有回答"目标方差与人类偏好"这两个问题，正是本文的切入点。

### 2.2 硬回报目标的方差与软目标线索

- **Learning to predict by the methods of temporal differences**（Sutton，1988，Machine Learning 3:9–44）— [DOI:10.1007/BF00115009](https://doi.org/10.1007/BF00115009)。提出 TD(λ) 与多步回报，给出回报估计中偏差与方差的权衡框架。**与本文（Soft-DMC / RLHF 校准）的关联**：DMC 用整局硬回报，等价于极长步数、极低偏差但极高方差的一端；Soft-DMC 的软目标可理解为把这一端向低方差侧移动，该文提供了最基础的理论语言。
- **Safe and Efficient Off-Policy Reinforcement Learning**（Munos 等，2016，NIPS 2016）— [NeurIPS 2016 论文页](https://proceedings.neurips.cc/paper/2016/hash/c3992e9a68c5ae12bd18488bc579b30d-Abstract.html)。提出 Retrace(λ)：低方差、可安全使用任意行为策略数据的回报估计。**与本文（Soft-DMC / RLHF 校准）的关联**：软目标需要"既低方差又不引入过大偏差"的回报构造，Retrace 的截断式多步回报是可选的技术底座之一。
- **Rainbow: Combining Improvements in Deep Reinforcement Learning**（Hessel 等，2018，AAAI 2018）— [DOI:10.1609/aaai.v32i1.11796](https://doi.org/10.1609/aaai.v32i1.11796)。把 n-step 回报、分布化价值、优先回放等组件整合，系统验证 n-step 回报对价值学习的收益。**与本文（Soft-DMC / RLHF 校准）的关联**：n-step 回报是"用更短的有效视野降低方差"的直接手段，支撑 Soft-DMC 中"软目标 = 有偏但低方差的回报构造"这一设计。
- **A Distributional Perspective on Reinforcement Learning**（Bellemare 等，2017，ICML 2017）— [PMLR 70:449–458](https://proceedings.mlr.press/v70/bellemare17a.html)。主张学习回报分布而非期望值，并给出分布化价值学习的理论与算法（C51）。**与本文（Soft-DMC / RLHF 校准）的关联**：分布化价值是 Soft-DMC 软目标的核心候选形式——用分布间的软比较替代点估计，可直接暴露"候选动作价值差小于估计误差"的情形，正是本文一步前瞻失效的机制。
- **Distilling the Knowledge in a Neural Network**（Hinton 等，2015，arXiv 预印本）— [arXiv:1503.02531](https://arxiv.org/abs/1503.02531)。提出用带温度的软标签（soft targets）蒸馏知识，软目标携带类间相似性信息。**与本文（Soft-DMC / RLHF 校准）的关联**：Soft-DMC 的"软"直接借用这一含义——把硬回报/硬标签换成带温度的软目标，降低目标噪声并保留候选动作之间的相对信息。
- **When does label smoothing help?**（Müller 等，2019，NeurIPS 2019）— [NeurIPS 2019 论文页](https://proceedings.neurips.cc/paper_files/paper/2019/hash/f1748d6b0fd9d439f71450117eba2725-Abstract.html)。系统分析 label smoothing 这类软目标如何抑制过自信、改善校准，并说明其对蒸馏的影响。**与本文（Soft-DMC / RLHF 校准）的关联**：本文观察到"价值网络越拟合训练分布、分布外错误越硬"（AUC 0.635 时错得软、0.700 时错得硬），该文为"软目标改善校准、抑制过自信"提供了直接依据，是 Soft-DMC 软目标设计的最近邻证据。

> **未找到可靠来源：以 Soft-DMC 命名的公开工作。** 检索词：`"Soft-DMC" reinforcement learning`、`"soft deep Monte Carlo"`、`"soft target" Monte Carlo card game`、`"Soft-DMC" GuanDan`。因此本文把"软目标 + 软采样"作为方法主张提出，其组件依据分散在 n-step 回报（Sutton 1988；Munos 等 2016）、分布化价值（Bellemare 等 2017；Hessel 等 2018）与软目标正则（Hinton 等 2015；Müller 等 2019）之中。

### 2.3 策略优化与并行采样（DMC 的对照）

- **Proximal Policy Optimization Algorithms**（Schulman 等，2017，arXiv 预印本）— [arXiv:1707.06347](https://arxiv.org/abs/1707.06347)。用裁剪的重要性采样比做稳定的策略梯度，是当前最常用的 on-policy 算法。**与本文（Soft-DMC / RLHF 校准）的关联**：PerfectDou 用 PPO + GAE 训练斗地主；Soft-DMC 的策略改进可用 PPO 式目标实现，而 RLHF 校准阶段的 KL 约束也常以 PPO 为载体，因此它是本文方法实现层面的参照。
- **IMPALA: Scalable Distributed Deep-RL with Importance Weighted Actor-Learner Architectures**（Espeholt 等，2018，ICML 2018）— [arXiv:1802.01561](https://arxiv.org/abs/1802.01561)。分布式 actor-learner + V-trace 离策略修正，支持大规模并行采样。**与本文（Soft-DMC / RLHF 校准）的关联**：本文的并行自对弈只是按种子切分子进程（4 进程 3.04×），瓶颈在 CPU 规则引擎；IMPALA 式架构是扩展到多机时的参考，也解释了为什么本文把算力投在"目标设计"而非"堆采样"上。
- **Asynchronous Methods for Deep Reinforcement Learning**（Mnih 等，2016，ICML 2016）— [arXiv:1602.01783](https://arxiv.org/abs/1602.01783)。A3C：多线程异步 actor 更新共享参数，是并行 RL 的早期范式。**与本文（Soft-DMC / RLHF 校准）的关联**：与 IMPALA 同理，它提供了并行采样的经典方案；本文实测吞吐瓶颈在引擎而非梯度同步，说明 Soft-DMC 的收益应来自目标与采样分布，而不是并行度。

### 2.4 模仿学习基线：为什么必须转向 RL 闭环

- **A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning**（Ross 等，2011，AISTATS 2011）— [arXiv:1011.0686](https://arxiv.org/abs/1011.0686)。DAgger 通过在线聚合专家纠正数据，解决行为克隆的分布漂移与复合误差。**与本文（Soft-DMC / RLHF 校准）的关联**：本文用 5000 局老师数据做纯 BC、对老师只有 51.50%，正是 BC 复合误差的天花板；DAgger 是低成本改进方向，但要让策略超过老师，仍需要 DMC/Soft-DMC 的回报信号与 RLHF 的偏好信号。

---

## 三、不完全信息博弈基准：掼蛋与斗地主

> **为什么用掼蛋做基准环境**：① **2v2 固定队伍合作**——需要团队信用分配与让牌，区别于斗地主的 1v2 与扑克的各自为战；② **万能牌（逢人配）**——同一手牌有多种解释，动作合法性与牌力估计耦合；③ **牌型阶梯**——单、对、三、顺、连对、飞机、炸弹、同花顺等，合法动作空间随局面剧烈变化；④ **长局高方差**——多轮、级牌与升级机制使单局回报稀疏且方差大，硬 DMC 的硬回报目标因此噪声更高。DanZero 需要 160 CPU + 1 GPU 训练 30 天才达到人类水平、DanZero+ 进一步才到压制级，说明该基准的计算门槛很高；这正是本文选择"方法分析 + 可复现负结果"而非"再刷一次棋力"的现实理由。
>
> **交叉引用**：DouZero（斗地主，DMC）、DanZero / DanZero+（掼蛋，分布式自对弈 DMC）的方法细节已在 §2.1 给出，本节不重复条目，只把它们当作基准环境的证据使用。

### 3.1 斗地主基准

- **PerfectDou: Dominating DouDizhu with Perfect Information Distillation**（Yang 等，2022，NeurIPS 2022）— [arXiv:2203.16406](https://arxiv.org/abs/2203.16406)。提出"完美信息训练、不完美信息执行"的完美信息蒸馏，配合 PPO + GAE 并行训练，在斗地主上超过已有程序。**与本文（Soft-DMC / RLHF 校准）的关联**：它给出绕开"不完美信息下价值估计不准"的一条路线——用完美信息教师直接教策略；本文没有完美信息教师，只能从硬回报学价值，AUC 0.635 的弱价值与前瞻失败正说明该路线在弱监督下的边界。

### 3.2 掼蛋基准

- **基于深度强化学习的掼蛋扑克博弈求解**（葛振兴、向帅、田品卓、高阳，2024，计算机研究与发展）— [文章页（crad.ict.ac.cn）](https://crad.ict.ac.cn/article/doi/10.7544/issn1000-1239.202220697)。国内团队用深度强化学习求解掼蛋，是该基准上直接相关的中文工作。**与本文（Soft-DMC / RLHF 校准）的关联**：同为掼蛋 RL 方向；本文的差异是明确以"软目标/软采样 + RLHF 校准"的方法路线与"可复现基线 + 诚实负结果"为目标，并公开规则引擎与评估协议，而不是追求最强棋力。
- **Mastering the Game of Guandan with Deep Reinforcement Learning and Behavior Regulating**（Yanggong、Pan、Wang，2024，arXiv 预印本）— [arXiv:2402.13582](https://arxiv.org/abs/2402.13582)。提出 GuanZero 框架，用蒙特卡洛方法 + 深度网络训练掼蛋智能体，核心贡献是通过网络编码方案调控智能体行为。**与本文（Soft-DMC / RLHF 校准）的关联**：同基准的蒙特卡洛路线，且同样承认"只追胜率不够"；它用编码调控行为，本文用软目标/软采样与 RLHF 校准调控策略分布，二者可对照"行为调控"的两种实现层次。
- **The Predictive–Optimization Gap in GuanDan Self-Play**（Zou 等，2026，arXiv 预印本）— [arXiv:2610.29411](https://arxiv.org/abs/2610.29411)。在掼蛋上用 DanZero 式蒙特卡洛自对弈做受控干预（以胜率预测器变化量作回合级监督），单条谱系可显著优于匹配基线，但 5 个预注册复现种子无一为正、10 种子合并区间含 0，作者据此提出"预测—优化鸿沟"。**与本文（Soft-DMC / RLHF 校准）的关联**：这是与本文最接近的负结果研究——它说明"能预测结果"不等于"能提供可靠的优化方向"；本文从价值目标方差与"全局 AUC ≠ 决策可用"的角度给出互补解释，并进一步提出软目标与 RLHF 校准作为应对。

### 3.3 相邻的不完全信息基准：麻将

- **Suphx: Mastering Mahjong with Deep Reinforcement Learning**（Li 等，2020，arXiv 预印本）— [arXiv:2003.13590](https://arxiv.org/abs/2003.13590)。用深度强化学习 + 全局奖励预测 + oracle guiding + 运行时策略自适应，在天凤平台稳定段位超过 99.99% 的官方排名人类玩家。**与本文（Soft-DMC / RLHF 校准）的关联**：同样是"四人 + 不完美信息 + 长局高方差"，Suphx 用 oracle guiding（训练时借完美信息、执行时不用）缓解价值估计难题；本文没有额外信息源，价值网络 AUC 只到 0.635/0.700，这解释了为什么本文转向"软化目标"而不是"借更多信息"。

---

## 四、RLHF 与策略校准

> RLHF 的标准流程是：人类成对偏好 → 奖励模型 → 在 KL 约束下优化策略。它在语言模型上成熟，但本文借用的是其**校准**含义：让强策略在"胜率"之外对齐人类对打法的偏好（可解释的牌路、不抛弃队友、不确定时保守），并用 KL 约束与早停防止奖励模型过优化。

### 4.1 从人类偏好到策略学习

- **Deep reinforcement learning from human preferences**（Christiano 等，2017，NIPS 2017）— [NeurIPS 2017 论文页](https://proceedings.neurips.cc/paper/2017/hash/d5e2c0adad503c91f91df240d0cd4e49-Abstract.html)。用人类对轨迹段的成对偏好训练奖励模型，再用 RL 优化策略，证明在缺乏显式奖励函数时也能学习复杂行为。**与本文（Soft-DMC / RLHF 校准）的关联**：这是 RLHF 的方法原型；本文把它迁移到不完全信息博弈——偏好对象从"轨迹段"变成"同一局面下的两个候选打法"，奖励模型输出用于策略校准。
- **Learning to summarize with human feedback**（Stiennon 等，2020，NeurIPS 2020）— [NeurIPS 2020 论文页](https://proceedings.neurips.cc/paper_files/paper/2020/hash/1f89885d556929e98d3ef9b86448f951-Abstract.html)。收集人类对摘要的成对比较，训练奖励模型并用 RL 微调摘要策略，显著优于监督学习与人工参考摘要。**与本文（Soft-DMC / RLHF 校准）的关联**：它示范了"偏好数据 + 奖励模型 + KL 约束 RL"的完整闭环；本文的校准流程（成对偏好 → 奖励模型 → KL 约束策略更新 → 偏好一致率与胜率保持的度量）直接沿用这一结构。
- **Training language models to follow instructions with human feedback**（Ouyang 等，2022，NeurIPS 2022）— [NeurIPS 2022 论文页](https://proceedings.neurips.cc/paper_files/paper/2022/hash/b1efde53be364a73914f58805a001731-Abstract-Conference.html)。InstructGPT：监督微调 + 偏好奖励模型 + PPO，使 1.3B 模型在人类评价上优于 175B GPT-3。**与本文（Soft-DMC / RLHF 校准）的关联**：它证明偏好信号可以在保持能力的同时显著改变策略行为；本文要验证的是同一问题在博弈策略上的版本——校准后胜率不显著下降、偏好一致率上升。
- **Fine-Tuning Language Models from Human Preferences**（Ziegler 等，2019，arXiv 预印本）— [arXiv:1909.08593](https://arxiv.org/abs/1909.08593)。在奖励中加入对参考策略的 KL 惩罚，约束策略不偏离预训练分布，是 RLHF 中 KL 约束的早期形式。**与本文（Soft-DMC / RLHF 校准）的关联**：本文的 RLHF 校准阶段采用同样的 KL 约束，防止策略为了偏好分数而崩坏棋力；这也是"校准 ≠ 重训"的关键实现细节。

### 4.2 偏好数据的替代与扩展

- **Training a Helpful and Harmless Assistant with Reinforcement Learning from Human Feedback**（Bai 等，2022，arXiv 预印本）— [arXiv:2204.05862](https://arxiv.org/abs/2204.05862)。构建有用/无害偏好数据并用 RLHF 训练助手，系统展示偏好数据规模与对齐效果的关系（HH-RLHF）。**与本文（Soft-DMC / RLHF 校准）的关联**：为"成对偏好数据 + 奖励模型"的工程可行性提供大规模证据；本文的偏好采集界面与协议设计可参照其数据组织方式。
- **Constitutional AI: Harmlessness from AI Feedback**（Bai 等，2022，arXiv 预印本）— [arXiv:2212.08073](https://arxiv.org/abs/2212.08073)。用一组原则（宪法）让模型自我批评并由 AI 反馈替代部分人类偏好标注（RLAIF）。**与本文（Soft-DMC / RLHF 校准）的关联**：提示了低成本偏好信号的来源；在博弈场景中可用规则/启发式代理部分人类偏好，但本文仍以人类成对偏好为主，以避免把"老师偏好"误当成"人类偏好"。
- **Direct Preference Optimization: Your Language Model is Secretly a Reward Model**（Rafailov 等，2023，NeurIPS 2023）— [NeurIPS 2023 论文页](https://papers.nips.cc/paper_files/paper/2023/hash/a85b405ed65c6477a4fe8302b5e06ce7-Abstract-Conference.html)。把 KL 约束下的奖励最大化解析为对偏好数据的分类损失，免去显式奖励模型与在线 RL。**与本文（Soft-DMC / RLHF 校准）的关联**：这是 RLHF 校准的轻量替代方案；若偏好数据规模有限，DPO 式目标比"奖励模型 + PPO"更稳，可作为本文校准阶段的降级实现。

### 4.3 校准与过优化

- **On Calibration of Modern Neural Networks**（Guo 等，2017，ICML 2017）— [PMLR 70:1321–1330](https://proceedings.mlr.press/v70/guo17a.html)。发现现代神经网络普遍校准不良，系统比较后处理校准方法，指出 temperature scaling 简单而有效。**与本文（Soft-DMC / RLHF 校准）的关联**：本文的"校准"有两层——概率校准（价值/偏好分数是否可信）与策略校准（是否符合人类偏好）；Guo 等提供第一层的工具与度量（ECE、温度缩放），可直接用于奖励模型与价值头的可靠性检查。
- **Scaling Laws for Reward Model Overoptimization**（Gao、Schulman、Hilton，2023，ICML 2023）— [PMLR 202:10835–10866](https://proceedings.mlr.press/v202/gao23h.html)。用合成"金标准奖励"测量代理奖励被过度优化时真实分数的退化，给出随模型规模与 KL 系数变化的 scaling law。**与本文（Soft-DMC / RLHF 校准）的关联**：这是 RLHF 校准阶段的核心风险——偏好奖励模型只是代理，过度优化会掉胜率；本文据此设计 KL 约束、早停与"胜率保持度"指标，而不是单纯最大化偏好分数。
- **A Survey of Reinforcement Learning from Human Feedback**（Kaufmann 等，2023，arXiv 预印本）— [arXiv:2312.14925](https://arxiv.org/abs/2312.14925)。系统梳理 RLHF 的偏好模型、奖励学习、KL 约束策略优化与评估方法。**与本文（Soft-DMC / RLHF 校准）的关联**：为本文的校准流程提供术语与分类框架（偏好模型、奖励模型、策略优化、KL 正则），也便于说明本文与语言模型 RLHF 的差异：这里的偏好对象是博弈动作而非文本。

> **未找到可靠来源：Zhu 等 2023 的 RLHF 综述。** 检索词：`Zhu 2023 survey reinforcement learning human feedback`、`"Zhu" "A Survey" RLHF`、`Zhu preference model survey 2023`。本轮检索未命中可信的 "Zhu 等 2023" 条目，故以 Kaufmann 等（2023）的综述替代；若后续找到该文，可在 4.3 节补入。

---

## 五、与本项目的对照表

| 工作 | 环境 | 核心方法 | 主要结果 | 与本文的关系 |
|---|---|---|---|---|
| PIMC（Long 等，2010） | 合成博弈树 + 牌类 | 确定化 + 完美信息搜索 | 给出 PIMC 强弱的可检测性质 | PIMC 的失效在信息集结构；本文的失效在价值目标与度量层，二者互补 |
| GIB（Ginsberg，2001） | 桥牌 | PIMC + 不完美信息推理 | 专家级桥牌 | 牌类 PIMC 实践；本文不做确定化搜索 |
| ISMCTS（Cowling 等，2012） | 牌类 | 信息集 MCTS | 从结构上规避 strategy fusion | 搜索层修补；本文在价值目标层修补 |
| AlphaZero（Silver 等，2018） | 围棋/国际象棋/将棋 | MCTS + 自对弈 | 超人类 | 搜索能改进策略/价值目标；本文显示弱价值下单步前瞻有害 |
| MuZero（Schrittwieser 等，2020） | 棋类/Atari | 学习隐式模型 + 规划 | 强表现 | 需可学模型；掼蛋有显式规则但隐藏手牌 |
| ReBeL（Brown 等，2020） | 单挑扑克等 | CFR 式搜索 + 深度 RL | 强表现 | 需反事实价值与两人零和结构，本文不适用 |
| Student of Games（Schmid 等，2023） | 围棋/国际象棋/扑克 | 统一搜索 + 学习 | 多博弈强表现 | 通用框架，未覆盖 2v2 合作与万能牌 |
| DeepStack（Moravčík 等，2017） | 单挑 NLHE | 反事实价值网络 + 持续重解 | 专家级 | 价值准是搜索有效的前提；本文给出该前提失效的反例 |
| Libratus / Pluribus（2018/2019） | 单挑 / 6 人 NLHE | CFR、自对弈 + 搜索 | 击败顶尖人类 | 零和或各自为战，无固定队友 |
| CFR / Deep CFR（2007/2019） | 扑克类 | 反事实后悔最小化（+ 神经网络） | 两人零和收敛到纳什 | 理论基座；4 人合作非零和不能直接套用 |
| DouZero（2021） | 斗地主 | DMC + 动作编码 + 并行 actor | Botzone 第 1（344 个智能体） | 硬 DMC 的代表；Soft-DMC 的直接对照 |
| DanZero（2023） | 掼蛋（4 人 2v2） | 分布式自对弈 + DMC | 超过 8 个启发式基线，达人类水平 | 同基准的强 RL；算力门槛高，本文改做方法分析 |
| DanZero+（2024） | 掼蛋 | 系统化 RL 扩展 | 压制级表现 | 同基准 SOTA，反衬本文负结果的受限设定 |
| PerfectDou（2022） | 斗地主 | 完美信息蒸馏 + PPO | SOTA | 用完美信息教师绕开价值估计，本文没有该教师 |
| Suphx（2020） | 麻将（4 人） | DRL + oracle guiding + 全局奖励预测 | 天凤平台 99.99% | 相邻不完全信息基准；本文无额外信息源 |
| 葛振兴等（2024） | 掼蛋 | 深度强化学习 | — | 国内同类工作；本文强调可复现与失效分析 |
| GuanZero（2024） | 掼蛋 | 蒙特卡洛 + 深度网络 + 行为调控编码 | 与 SOTA 对比有效 | 同基准蒙特卡洛路线；本文用软目标/RLHF 校准做行为调控 |
| Zou 等（2026） | 掼蛋 | DanZero 式 DMC + 进度预测干预 | 5 个预注册种子无正效应，合并区间含 0 | 最接近的负结果；本文补上价值目标方差与指标解释 |
| **本工作** | **掼蛋（仅作基准环境）** | **Soft-DMC（软目标 + 软采样）+ RLHF 策略校准** | **BC 51.50%；AUC 0.635→0.700；前瞻 26.00%→16.50%** | — |

---

## 六、本文的定位与边界

1. **定位是方法路线，不是棋力 SOTA。** 本文属于「不完全信息博弈 + 强化学习」，贡献是 **Soft-DMC（软目标 + 软采样）+ RLHF 校准** 这条方法路线的**可复现基准与失效分析**；掼蛋只是承载实验的基准环境。不追求击败 DanZero/DanZero+，也不与人类高手比棋力。
2. **与 DMC 文献的差别在"目标"而非"规模"。** DouZero / DanZero / DanZero+ 证明硬回报 DMC 在大算力下可行；本文问的是另一个问题：在 2v2 合作、长视野、高方差的设定里，硬回报目标方差过大、候选动作价值差小于估计误差，搜索会被错误价值带偏。已有负结果（BC 51.50% → 一步前瞻 26.00%；AUC 0.635 → 0.700 反而使前瞻降到 16.50%）是提出软目标与软采样的直接依据，而不是"训练不够"的托词。
3. **与 PIMC/搜索文献的差别在"层次"。** Long 等（2010）、ISMCTS（2012）、PIMC postponing（2024）修补的是信息集结构与确定化缺陷；本文承认这些缺陷，但指出还有一层独立的失效：价值目标的噪声与全局 AUC 的指标错位。因此本文不加深搜索、不做多步前瞻，而是先修价值目标与度量。
4. **与 RLHF 文献的差别在"对象"。** Christiano 等（2017）到 Ouyang 等（2022）的 RLHF 校准的是文本生成；本文校准的是**博弈动作策略**，偏好对象是同一局面下的候选打法。度量也从"人类偏好胜率"扩展为偏好一致率、与人类选择的 KL、以及校准后的胜率保持度；同时用 KL 约束与早停防止奖励模型过优化（Gao 等 2023 的 scaling law）。
5. **边界不外推。** Soft-DMC 的软动作采样已实现，软价值目标与 RLHF 校准尚在设计中；所有结论限于当前设定（手工特征 v2/v3、5000 局老师数据、200 局配对评估、Wilson 区间），不能外推为"掼蛋不可搜索"或"掼蛋策略只能到 51.50%"。本文不声称软目标是唯一解，只声称它是当前负结果所指向的、可检验的下一步。
