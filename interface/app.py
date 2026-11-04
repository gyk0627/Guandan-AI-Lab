"""掼蛋人机对战 —— 打包成 exe 时用的启动器。

双击 exe 后：
  1. 自动挑一个没被占用的端口
  2. 在浏览器里打开游戏页面
  3. 关掉这个黑窗口，游戏就结束

和仓库里跑 `python -m interface.web_server` 的效果一样，只是不需要装 Python。
打包版用**启发式策略**（会打牌的规则 AI）。神经网络要 PyTorch（2GB 以上），
不进 exe；想在仓库里用神经网络，直接跑网页版或训练好的模型即可。
"""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path


def application_dir() -> Path:
    """exe 所在的文件夹；从源码运行时是仓库根目录。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def pick_port(server_module, requested, level, log_dir, attempts=20):
    """从 requested 开始往后找一个能监听的端口。"""
    last_error = None
    for offset in range(attempts):
        port = requested + offset
        try:
            server = server_module.create_server(
                port=port,
                level=level,
                use_neural=False,
                log_dir=log_dir,
            )
        except OSError as error:  # 端口被占
            last_error = error
            continue
        if offset:
            print(f"端口 {requested} 被占用，改用 {port}。")
        return server, port
    raise SystemExit(f"从 {requested} 起的 {attempts} 个端口都打不开：{last_error}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="掼蛋人机对战（exe 版启动器）")
    parser.add_argument("--port", type=int, default=8765, help="起始端口，被占用会自动往后找")
    parser.add_argument("--level", default="2", help="打几，例如 2 / 7 / A")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)

    base = application_dir()
    log_dir = base / "replay"

    from interface import web_server

    server, port = pick_port(web_server, args.port, args.level, log_dir)
    url = f"http://127.0.0.1:{port}/"

    print("=" * 58)
    print("掼蛋人机对战")
    print("=" * 58)
    print(f"地址：{url}")
    print("你是 0 号位（A 队），队友 2 号位；对手是 1、3 号位")
    print(f"级牌：{args.level}    策略：启发式")
    print(f"对局记录会存到：{log_dir}")
    print("关闭本窗口即结束。按 Ctrl+C 也可以。")
    print("如果浏览器没自动打开，把上面的地址复制到浏览器里。")
    print("=" * 58)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
