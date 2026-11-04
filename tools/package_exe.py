"""一键出「双击即玩」的发布包：打包 exe → 写使用说明 → 压成 zip。

用法（仓库根目录）：

    # 1) 离线版：朋友打完点「导出对局」，把文件发回来
    python -m tools.package_exe

    # 2) 一键发邮件版：朋友点「发送给作者」，记录直接进你的邮箱（推荐）
    python -m tools.package_exe --email you@example.com ^
        --smtp-host smtp.qq.com --smtp-user you@example.com --smtp-password 授权码

    # 3) 自动上传版：自己开接收端时用
    python -m tools.package_exe --upload-url http://192.168.1.10:8790/upload --token mytoken

给 `--email` 时发布包会写入 `mail.json`，朋友解压双击就能玩，打完点一下按钮就发到你邮箱，
**不需要改任何文件、不需要装邮件客户端**。

注意：`mail.json` 里的 SMTP 密码会随包分发，拿到包的人能解出来。
请使用「专用邮箱 + 授权码」，不要用个人主邮箱的登录密码。

产物：
    dist/GuandanAI/GuandanAI.exe        双击就能玩
    dist/GuandanAI/使用说明.txt
    dist/GuandanAI/mail.json            仅 --email 时
    dist/GuandanAI/upload.json          仅 --upload-url 时
    dist/GuandanAI-win64.zip            可以直接发给别人
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

from tools.build_exe import build

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "dist"

README_HEAD = """掼蛋人机对战 —— 使用说明
==============================

一、怎么开始
  1. 把整个 GuandanAI 文件夹解压到任意位置（不要只复制 exe，它旁边的文件也要）
  2. 双击 GuandanAI.exe
  3. 会弹出一个独立窗口（有自己的标题栏，没有地址栏、没有标签页），
     窗口里就是牌桌。第一次启动要等两三秒。
  4. 关掉游戏窗口，程序就退出了

  窗口用的是 Windows 自带的 WebView2 组件（Win11 自带；Win10 一般随 Edge 装好）。
  万一你的系统缺这个组件，程序会提示一句，然后自动改用默认浏览器打开。

二、你和谁打
  你 = 0 号位（A 队），队友 = 2 号位（A 队）
  对手 = 1 号位（B 队）、3 号位（B 队）

三、规则要点
  - 连对必须正好 3 对（334455 可以，3344 不行）
  - 连续飞机必须正好 2 组三张（333444 可以，333444555 不行）
  - 顺子正好 5 张，可以带 2，不能带王，A2345 不算顺子
  - 红桃级牌是逢人配，可以顶替任何一张牌
  - 炸弹：4 张 < 同花顺 < 5 张 < 6 张 …… 8 张，没有四王炸
  - 不能压队友的牌（队友刚出过，你只能过）

四、AI 是什么水平
  打包版用「启发式」规则 AI：会算怎么把手牌拆得最快出完，
  会抢先手、会给队友让路，但不记牌、不猜牌，也看不到历史。
  在实验室里，它和神经网络版本打成 53 : 47 左右，属于同一档次。

五、对局记录
  每局都会自动存一份到 replay 文件夹。
"""

MAIL_HINT = """
六、把记录发回来（一步）
  打完一局，点窗口右上角的「发送给作者」按钮，它会自动把这一局打包发到作者邮箱，
  你什么都不用填、什么都不用装。

  万一网络不通（比如公司网络封了邮箱端口），按钮会告诉你文件存在哪，
  通常在你的「下载」文件夹，把那个 zip 发给组织者也可以。
  发送按钮随时可以点，打一半也能发。
"""

EXPORT_HINT = """
六、把记录发回来（一步）
  打完一局，点窗口右上角的「导出对局」按钮，
  文件会存到你的「下载」文件夹（文件名以 human_ 开头）。
  把这个文件发给组织者就行，别的都不用管。
  这个按钮随时可以点，打一半也能导出。
"""

UPLOAD_HINT = """
六、记录会自动传回来（无需操作）
  这个版本已经配好回传地址，每打完一局会自动上传，你什么都不用做。
  传不上去也没关系：会先存在本地，下次启动程序时接着传。
  如果一直传不上去，也可以点右上角「发送给作者」或「导出对局」。
"""

README_TAIL = """
七、常见问题
  - 提示「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」
  - 端口被占用：程序会自动换一个端口，看窗口里打印的地址
  - 想换打几：现在默认打 2；需要别的话用命令行 GuandanAI.exe --level 7
  - 想只用浏览器打开：GuandanAI.exe --browser
  - 不想上传：GuandanAI.exe --no-upload
"""


def make_readme(upload_configured=False, mail_configured=False):
    """使用说明：优先讲「一键发送」，其次「自动上传」，最后才是「手动导出」。"""
    if mail_configured:
        middle = MAIL_HINT
    elif upload_configured:
        middle = UPLOAD_HINT
    else:
        middle = EXPORT_HINT
    return README_HEAD + middle + README_TAIL


def write_upload_config(folder, url, token):
    """把上传地址写进发布包；返回写出的文件路径。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "upload.json"
    path.write_text(
        json.dumps({"url": url, "token": token}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def write_mail_config(folder, to, host, port, user, password, use_ssl=True, timeout=40.0):
    """把收件邮箱写进发布包；返回写出的文件路径。

    密码跟着包一起发出去，所以这里只接受「授权码」这类可随时吊销的凭据。
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "mail.json"
    path.write_text(
        json.dumps(
            {
                "to": to,
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "ssl": bool(use_ssl),
                "timeout": float(timeout),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打发布包")
    parser.add_argument("--name", default="GuandanAI")
    parser.add_argument("--upload-url", default=None, help="回传地址；给了就预先配好，朋友无需改动")
    parser.add_argument("--token", default="guandan-local", help="回传口令（配合 --upload-url）")
    parser.add_argument("--email", default=None, help="收件邮箱；给了就在界面上开「发送给作者」")
    parser.add_argument("--smtp-host", default=None, help="发信服务器，如 smtp.qq.com")
    parser.add_argument("--smtp-port", type=int, default=465)
    parser.add_argument("--smtp-user", default=None, help="发信账号（通常和 --email 相同）")
    parser.add_argument("--smtp-password", default=None, help="SMTP 授权码（不是登录密码）")
    parser.add_argument("--smtp-no-ssl", action="store_true", help="改用 STARTTLS（端口 587）")
    args = parser.parse_args(argv)

    if args.upload_url and not args.upload_url.startswith(("http://", "https://")):
        raise SystemExit("--upload-url 必须以 http:// 或 https:// 开头")

    if args.email:
        missing = [
            name
            for name, value in (
                ("--smtp-host", args.smtp_host),
                ("--smtp-user", args.smtp_user),
                ("--smtp-password", args.smtp_password),
            )
            if not value
        ]
        if missing:
            raise SystemExit("给了 --email 还要给：" + "、".join(missing))

    exe = build(name=args.name, clean=True, one_file=False, keep_work=False)
    folder = exe.parent

    mail_configured = bool(args.email)
    readme = folder / "使用说明.txt"
    readme.write_text(make_readme(bool(args.upload_url), mail_configured), encoding="utf-8-sig")

    if mail_configured:
        path = write_mail_config(
            folder,
            to=args.email,
            host=args.smtp_host,
            port=args.smtp_port,
            user=args.smtp_user,
            password=args.smtp_password,
            use_ssl=not args.smtp_no_ssl,
        )
        print(f"已写入邮箱配置：{path}")
        print("注意：这个密码会随包分发，请确认用的是专用邮箱的授权码。")

    if args.upload_url:
        path = write_upload_config(folder, args.upload_url, args.token)
        print(f"已写入回传配置：{path}")
    elif not mail_configured:
        (folder / "upload.json.example").write_text(
            json.dumps(
                {"url": "http://收集方的地址:8790/upload", "token": "收集方给你的口令"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    zip_path = DIST / f"{args.name}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path(folder.name) / path.relative_to(folder))

    total = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
    print()
    print(f"程序文件夹：{folder}  ({total / 1024 / 1024:.1f} MB)")
    print(f"发布包：{zip_path}  ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print("把这个 zip 解压，双击里面的 exe 就能玩。")
    if mail_configured:
        print("朋友打完后点「发送给作者」，记录会直接进你的邮箱。")
    elif args.upload_url:
        print("朋友解压后无需任何配置，每局自动回传。")
    else:
        print("朋友打完后点「导出对局」，把下载的文件发回来。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
