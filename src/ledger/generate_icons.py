#!/usr/bin/env python3
"""
生成 PWA 图标
使用 Pillow 库生成不同尺寸的应用图标
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def create_icon(size: int, output_path: Path, maskable: bool = False) -> None:
    """
    创建一个图标

    Args:
        size: 图标尺寸（正方形）
        output_path: 输出文件路径
        maskable: 是否创建 maskable 图标（需要安全区域）
    """
    # 创建图像（深色背景）
    bg_color = (15, 23, 42)  # --color-background
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # 如果是 maskable 图标，添加安全区域（20%）
    if maskable:
        safe_zone = int(size * 0.2)
        inner_size = size - 2 * safe_zone
        offset = safe_zone
    else:
        inner_size = int(size * 0.8)
        offset = int(size * 0.1)

    # 绘制圆角矩形背景（金色）
    accent_color = (245, 158, 11)  # --color-primary
    corner_radius = inner_size // 8

    # 绘制圆角矩形
    draw.rounded_rectangle(
        [offset, offset, offset + inner_size, offset + inner_size],
        radius=corner_radius,
        fill=accent_color,
    )

    # 绘制图标内容（简化的货币符号）
    # 绘制 ¥ 符号
    symbol_color = (15, 23, 42)  # 深色文字
    line_width = max(2, inner_size // 20)

    # Y 的两条斜线
    y_top = offset + inner_size * 0.25
    y_middle = offset + inner_size * 0.5
    y_bottom = offset + inner_size * 0.75
    x_center = offset + inner_size // 2
    x_left = offset + inner_size * 0.3
    x_right = offset + inner_size * 0.7

    # 左斜线
    draw.line([(x_left, y_top), (x_center, y_middle)], fill=symbol_color, width=line_width)

    # 右斜线
    draw.line([(x_right, y_top), (x_center, y_middle)], fill=symbol_color, width=line_width)

    # 中间竖线
    draw.line([(x_center, y_middle), (x_center, y_bottom)], fill=symbol_color, width=line_width)

    # 两条横线
    h_line_top = offset + inner_size * 0.42
    h_line_bottom = offset + inner_size * 0.52
    h_line_left = offset + inner_size * 0.25
    h_line_right = offset + inner_size * 0.75

    draw.line(
        [(h_line_left, h_line_top), (h_line_right, h_line_top)], fill=symbol_color, width=line_width
    )

    draw.line(
        [(h_line_left, h_line_bottom), (h_line_right, h_line_bottom)],
        fill=symbol_color,
        width=line_width,
    )

    # 保存图标
    img.save(output_path, "PNG", optimize=True)
    print(f"已生成: {output_path.name} ({size}x{size})")


def main():
    """生成所有需要的图标尺寸"""
    # 确定图标输出目录
    script_dir = Path(__file__).parent
    icons_dir = script_dir / "icons"
    icons_dir.mkdir(exist_ok=True)

    print("开始生成 PWA 图标...")
    print()

    # 标准图标尺寸
    standard_sizes = [72, 96, 128, 144, 152, 192, 384, 512]

    for size in standard_sizes:
        output_path = icons_dir / f"icon-{size}.png"
        create_icon(size, output_path, maskable=False)

    print()
    print("生成 maskable 图标...")
    print()

    # Maskable 图标（带安全区域）
    maskable_sizes = [192, 512]

    for size in maskable_sizes:
        output_path = icons_dir / f"icon-maskable-{size}.png"
        create_icon(size, output_path, maskable=True)

    print()
    print("图标生成完成！")
    print()
    print(f"图标位置: {icons_dir.absolute()}")
    print()
    print("提示：")
    print("  - 标准图标适用于大多数设备")
    print("  - Maskable 图标适用于支持自适应图标的 Android 设备")
    print("  - 可以使用在线工具进一步优化图标：https://realfavicongenerator.net/")


if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("错误：需要安装 Pillow 库")
        print()
        print("请运行以下命令安装：")
        print("  pip install Pillow")
        print("或")
        print("  uv pip install Pillow")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
