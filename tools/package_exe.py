"""一键出「双击即玩」的发布包：打包 exe → 写使用说明 → 压成 zip。

用法（仓库根目录）：
    python -m tools.package_exe

产物：
    dist/GuandanAI/GuandanAI.exe        双击就能玩
    dist/GuandanAI/使用说明.txt
    dist/GuandanAI-win64.zip            可以直接发给别人
"""

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from tools.build_exe import build

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "dist"

README = """掼蛋人机对战 —— 使用说明
==============================

一、怎么开始
  1. 把整个 GuandanAI 文件夹解压到任意位置（不要只复制 exe，它旁边的文件也要）
  2. 双击 GuandanAI.exe
  3. 会弹出一个独立的游戏窗口（没有地址栏和标签页，和普通软件一样）
     第一次启动要等几秒（Windows 在初始化窗口），窗口里如果是空白的，
     按一下 F5 刷新即可；万一窗口根本没弹出来，把黑色窗口里显示的地址
     复制到浏览器也能玩
  4. 关掉游戏窗口，程序就退出了

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
  每局都会自动存一份到 replay 文件夹，可以用来看回放、复盘。

六、把对局记录传回来（可选）
  默认只在你自己电脑上存着，不会上传。
  想让它自动传回：把 upload.json.example 改名成 upload.json，
  把里面的地址和口令换成收集方给的，再启动程序就行。
  传不上去也没关系，会先存在本地，下次启动接着传。

七、常见问题
  - 提示「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」
  - 端口被占用：程序会自动换一个端口，看窗口里打印的地址
  - 想换打几：现在默认打 2；需要别的话用命令行 GuandanAI.exe --level 7
  - 想只用浏览器打开：GuandanAI.exe --browser
  - 不想上传：GuandanAI.exe --no-upload
"""

UPLOAD_EXAMPLE = """{
  "url": "http://收集方的地址:8790/upload",
  "token": "收集方给你的口令"
}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打发布包")
    parser.add_argument("--name", default="GuandanAI")
    args = parser.parse_args(argv)

    exe = build(name=args.name, clean=True, one_file=False, keep_work=False)
    folder = exe.parent

    readme = folder / "使用说明.txt"
    readme.write_text(README, encoding="utf-8-sig")
    (folder / "upload.json.example").write_text(UPLOAD_EXAMPLE, encoding="utf-8")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
