"""端到端冒烟测试：启动打包好的 exe，真的打完一局，再检查对局记录。

用法：
    python -m tools.exe_smoke --exe dist/GuandanAI.exe
    python -m tools.exe_smoke --url http://127.0.0.1:8765/     # 测已经在跑的界面

做三件事：
  1. 起 exe（或连已有地址），等它响应
  2. 用「提示」里的第一手一直打到结束（能过就过）
  3. 确认真的打完了、排名 4 个、对局记录文件有内容
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(url: str, payload=None, timeout=10):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def wait_ready(base: str, timeout=40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base, timeout=2) as response:  # noqa: S310
                return response.status
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.4)
    raise SystemExit(f"{timeout:.0f} 秒内没等到界面启动：{base}")


def play_one_game(base: str, level: str, max_steps: int = 400) -> dict:
    state = request(f"{base}api/new", {"level": level, "use_neural": False})
    steps = 0
    plays = passes = 0

    while not state.get("game_over"):
        steps += 1
        if steps > max_steps:
            raise SystemExit(f"超过 {max_steps} 步还没打完，可能卡住了")
        if not state.get("your_turn"):
            raise SystemExit("没轮到你却也没结束，服务端没把 AI 走完")
        hint = request(f"{base}api/legal")
        moves = hint.get("plays") or []
        if moves:
            state = request(f"{base}api/play", {"cards": moves[0]})
            plays += 1
        else:
            state = request(f"{base}api/pass", {})
            passes += 1
    return {"state": state, "steps": steps, "plays": plays, "passes": passes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="exe 端到端冒烟测试")
    parser.add_argument("--exe", default=None, help="exe 路径；给了就自己起进程")
    parser.add_argument("--url", default=None, help="已有界面的地址，例如 http://127.0.0.1:8765/")
    parser.add_argument("--port", type=int, default=8802)
    parser.add_argument("--level", default="7")
    args = parser.parse_args(argv)

    if not args.exe and not args.url:
        parser.error("--exe 和 --url 至少给一个")

    process = None
    replay_dir = None
    if args.exe:
        exe = Path(args.exe).resolve()
        if not exe.exists():
            raise SystemExit(f"找不到 exe：{exe}")
        replay_dir = exe.parent / "replay"
        before = {p.name for p in replay_dir.glob("human_*.jsonl")} if replay_dir.exists() else set()
        print(f"启动 {exe.name}（端口 {args.port}）……")
        process = subprocess.Popen(  # noqa: S603
            [str(exe), "--port", str(args.port), "--no-browser"],
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{args.port}/"
    else:
        base = args.url if args.url.endswith("/") else args.url + "/"
        before = None

    try:
        wait_ready(base)
        print("界面已响应，开始打一局……")
        started = time.time()
        result = play_one_game(base, args.level)
        elapsed = time.time() - started
        state = result["state"]
        ranking = state.get("ranking") or []
        print(f"打完：{elapsed:.1f} 秒，{result['steps']} 步，出牌 {result['plays']} 次、过牌 {result['passes']} 次")
        print(f"排名：{ranking}")
        print(f"日志名：{state.get('log_name')}")
        print(f"提示：{state.get('message')}")
        if len(ranking) != 4:
            raise SystemExit(f"排名应该有 4 个人，实际 {len(ranking)} 个")

        if replay_dir is not None:
            files = sorted(replay_dir.glob("human_*.jsonl"))
            new = [p for p in files if p.name not in before]
            if not new:
                raise SystemExit(f"没找到本局的对局记录（目录 {replay_dir}）")
            log = new[-1]
            lines = sum(1 for _ in log.open(encoding="utf-8"))
            print(f"对局记录：{log.name}，{lines} 行，{log.stat().st_size / 1024:.1f} KB")
            if lines < 10:
                raise SystemExit("对局记录行数太少，可能没记全")
        print("通过")
        return 0
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
