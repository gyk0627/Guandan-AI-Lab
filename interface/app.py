"""掼蛋人机对战 —— 打包成 exe 时用的启动器。

双击 exe 后：
  1. 自动挑一个没被占用的端口，在本机起服务
  2. 开一个独立应用窗口（没有地址栏和标签页）把游戏装进去
  3. 每局打完，如果 exe 旁边有 upload.json，就悄悄把记录传回去

和仓库里跑 `python -m interface.web_server` 的效果一样，只是不需要装 Python。
打包版用**启发式策略**（会打牌的规则 AI）。神经网络要 PyTorch（2GB 以上），
不进 exe；想在仓库里用神经网络，直接跑网页版或训练好的模型即可。
"""

import argparse
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def application_dir() -> Path:
    """exe 所在的文件夹；从源码运行时是仓库根目录。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_elevated() -> bool:
    """当前进程是不是以管理员权限在跑。"""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # 非 Windows 或调用失败时按「不是管理员」处理
        return False


def drop_admin_command(argv=None) -> list:
    """用 runas 的受限令牌把程序重新拉起来（权限降为普通用户）。

    Edge 不接受「管理员权限的浏览器」，在关闭 UAC 的机器上双击 exe 会继承
    管理员令牌，窗口就会一片空白。受限令牌（trustlevel 0x20000）不需要密码，
    降到普通用户后 Edge 才肯正常渲染。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [item for item in argv if item != "--relaunched"]
    if getattr(sys, "frozen", False):
        prefix = [sys.executable]
    else:
        prefix = [sys.executable, "-X", "utf8", "-m", "interface.app"]
    command = subprocess.list2cmdline(prefix + argv + ["--relaunched"])
    return ["runas", "/trustlevel:0x20000", command]


def relaunch_without_admin() -> bool:
    """降权重启；成功返回 True（调用方应立刻退出）。"""
    try:
        subprocess.Popen(
            drop_admin_command(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return True


def pick_port(server_module, requested, level, log_dir, attempts=20, on_log_ready=None):
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
                on_log_ready=on_log_ready,
            )
        except OSError as error:  # 端口被占
            last_error = error
            continue
        if offset:
            print(f"端口 {requested} 被占用，改用 {port}。")
        return server, port
    raise SystemExit(f"从 {requested} 起的 {attempts} 个端口都打不开：{last_error}")


def wait_until_ready(url, timeout=8.0):
    """等本地服务真的能应答，再开窗口。

    Edge 的应用模式在「服务还没起来」时开窗会得到一张白页；先探一下再开，
    启动慢的机器上就不会闪白屏了。
    """
    import urllib.request

    probe = url.rstrip("/") + "/api/state"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def start_uploader(base, log_dir, disabled=False):
    """有 upload.json 就起后台上传线程；没有就完全离线。"""
    from interface.uploader import Uploader

    uploader = Uploader(
        log_dir=log_dir,
        config_path=base / "upload.json",
        state_path=base / "upload_state.json",
    )
    if disabled:
        return None
    if not uploader.enabled:
        return None
    uploader.start()
    waiting = uploader.pending_count
    print("对局记录会自动回传（可在 upload.json 里关掉）。")
    if waiting:
        print(f"上次没传完的记录还有 {waiting} 条，正在补传。")
    return uploader


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="掼蛋人机对战（桌面版启动器）")
    parser.add_argument("--port", type=int, default=8765, help="起始端口，被占用会自动往后找")
    parser.add_argument("--level", default="2", help="打几，例如 2 / 7 / A")
    parser.add_argument("--no-browser", action="store_true", help="只起服务，不开任何窗口（测试用）")
    parser.add_argument("--browser", action="store_true", help="改用系统默认浏览器打开")
    parser.add_argument("--no-upload", action="store_true", help="本次不传对局记录")
    parser.add_argument("--home", default=None, help="数据目录（默认是 exe 所在文件夹；测试用）")
    parser.add_argument("--relaunched", action="store_true", help="内部用：已经降权重启过，别再重启")
    args = parser.parse_args(argv)

    # 以前用「Edge 应用模式」时，管理员权限会导致白窗，所以先降权重启。
    # 现在窗口是内嵌的 WebView2 控件，不受浏览器权限策略影响，不需要再重启。

    base = Path(args.home).resolve() if args.home else application_dir()
    log_dir = base / "replay"

    from interface import web_server

    uploader = start_uploader(base, log_dir, disabled=args.no_upload)
    callback = uploader.enqueue if uploader else None

    server, port = pick_port(
        web_server, args.port, args.level, log_dir, on_log_ready=callback
    )
    url = f"http://127.0.0.1:{port}/"

    print("=" * 58)
    print("掼蛋人机对战")
    print("=" * 58)
    print(f"地址：{url}")
    print("你是 0 号位（A 队），队友 2 号位；对手是 1、3 号位")
    print(f"级牌：{args.level}    策略：启发式")
    print(f"对局记录会存到：{log_dir}")
    print("关闭游戏窗口即结束。")
    print("=" * 58)

    serving = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    serving.start()

    window = None
    started = time.time()
    if not args.no_browser:
        if not wait_until_ready(url):
            print("服务启动较慢，仍然尝试打开窗口……")
        else:
            print("正在打开游戏窗口（第一次启动需要几秒）……")
        if args.browser:
            webbrowser.open(url)
        else:
            from interface.window import open_window

            window, kind = open_window(url, base / "window-profile")
            if window is None:
                print("没有可用的窗口组件，改用默认浏览器打开。")
                webbrowser.open(url)
            elif kind == "host":
                print("窗口已打开；关掉窗口就退出。")
            else:
                print("窗口空白就按一下 F5 刷新。")

    try:
        if window is not None:
            window.wait()  # 窗口关掉就退出
            if time.time() - started < 5 and not web_server.Handler.page_served:
                # 进程一闪而过、页面也没被请求过：窗口没起来（例如缺 WebView2 运行时）
                print("窗口没能打开，改用默认浏览器。")
                webbrowser.open(url)
                serving.join()
        else:
            serving.join()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        if uploader is not None:
            uploader.stop()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
