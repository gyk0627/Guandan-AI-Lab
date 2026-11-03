# interface/ —— 人机对战界面

本地网页版：Python 标准库起一个只监听 `127.0.0.1` 的小服务，浏览器打开就能和 AI 打。
**不需要联网，也不需要额外装包**（不需要 Flask、不需要 Node）。

## 怎么开

**方式一（推荐给日常使用）**：双击 `interface\start_gui.bat`，浏览器会自动打开。

**方式二（命令行）**：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
& .\.venv\Scripts\python.exe -m interface.web_server
```

然后打开 <http://127.0.0.1:8765/>。

常用参数：

| 参数 | 作用 |
|---|---|
| `--level 7` | 本局打 7（默认打 2） |
| `--port 8899` | 换端口（端口被占用时用） |
| `--no-neural` | 强制用启发式 AI（排查问题时用） |
| `--model models\xxx.pt` | 指定模型；省略则取 `models/` 下最新的 |
| `--no-browser` | 不自动开浏览器 |

## 怎么玩

- 你固定坐 **0 号位（A 队）**，队友是 2 号位，对手是 1、3 号位。
- 点手牌选中（再点取消），按 **出牌**；不想接就按 **过牌**。
- **提示**会列出几种可行出牌，点一下就自动帮你选好。
- 界面顶部可以换「打几」，点 **新的一局** 生效。

## 设计约束（为什么它不能作弊）

- 全部游戏状态都在服务端，浏览器只是一个显示层。
- 浏览器提交的每个动作都会经过 `GameState.play()` 校验：
  牌不在手里、牌型不合法、没轮到你、领出阶段过牌，都会被拒绝并返回原因。
- 因此**改前端、改 JS、直接发 HTTP 请求都没有用**，规则由服务端说了算。

## 已知限制

- 单人本地用，没做多用户会话隔离（同时开两个浏览器标签会共用同一局）。
- 界面没有动画、没有音效，牌面是文字 + 花色符号。
- AI 的强度取决于 `models/` 里最新的模型；目前是行为克隆的 51.5% 版本
  （见 [models/README.md](../models/README.md)），**不是强化学习产物**。

## 自测

界面有一套端到端测试，会在本机随机端口起服务、用真实 HTTP 请求把一整局打完：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_web.py -q
```
