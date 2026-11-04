"""生成 exe 图标：深绿圆角底 + 一张白色扑克牌 + 红桃。

不依赖外部图片，纯 Pillow 画图，方便以后重新生成。
用法：python make_icon.py <输出路径>
"""

import sys
from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]
CANVAS = 256

BACKGROUND = (10, 61, 44, 255)
CARD = (252, 251, 246, 255)
CARD_EDGE = (216, 190, 136, 255)
RED = (198, 38, 54, 255)
SHADOW = (4, 30, 22, 120)


def heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, color) -> None:
    """画一颗红桃：两个圆 + 一个三角。"""
    draw.ellipse([cx - radius, cy - radius + radius * 0.15, cx - radius * 0.05, cy + radius * 0.25], fill=color)
    draw.ellipse([cx + radius * 0.05, cy - radius + radius * 0.15, cx + radius, cy + radius * 0.25], fill=color)
    draw.polygon(
        [
            (cx - radius * 0.92, cy - radius * 0.1),
            (cx + radius * 0.92, cy - radius * 0.1),
            (cx, cy + radius * 1.15),
        ],
        fill=color,
    )


def build(size: int = 256) -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([4, 4, 252, 252], radius=58, fill=BACKGROUND)

    width, height = 128, 178
    left, top = (CANVAS - width) // 2, (CANVAS - height) // 2
    radius = 14

    draw.rounded_rectangle(
        [left + 5, top + 7, left + width + 5, top + height + 7],
        radius=radius,
        fill=SHADOW,
    )
    draw.rounded_rectangle(
        [left, top, left + width, top + height],
        radius=radius,
        fill=CARD,
        outline=CARD_EDGE,
        width=4,
    )

    # 牌面：中间一颗大红桃，左上角一颗小的（像真扑克牌的角标）
    heart(draw, CANVAS / 2, top + height * 0.46, 27, RED)
    heart(draw, left + 26, top + 30, 9, RED)

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "guandan.ico"
    images = [build(size) for size in SIZES]
    images[0].save(out, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"saved {out}")
    for size, image in zip(SIZES, images):
        image.save(out.replace(".ico", f"_{size}.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
