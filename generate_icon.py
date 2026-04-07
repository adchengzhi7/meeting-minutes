#!/usr/bin/env python3
"""產生會議記錄 App 圖示 (.icns)"""

import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent / "icon.iconset"


def draw_icon(size: int) -> Image.Image:
    """畫一個簡約風格的麥克風 + 文件圖示"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size * 0.08
    s = size  # shorthand

    # 背景：圓角矩形（深藍漸層感）
    r = s * 0.22
    draw.rounded_rectangle(
        [pad, pad, s - pad, s - pad],
        radius=r,
        fill=(37, 99, 235),  # blue-600
    )

    # 文件圖示（右下，白色半透明）
    doc_l = s * 0.42
    doc_t = s * 0.35
    doc_r = s * 0.78
    doc_b = s * 0.82
    doc_r_radius = s * 0.04

    draw.rounded_rectangle(
        [doc_l, doc_t, doc_r, doc_b],
        radius=doc_r_radius,
        fill=(255, 255, 255, 200),
    )

    # 文件上的橫線（模擬文字）
    line_color = (37, 99, 235, 120)
    lh = max(1, int(s * 0.02))
    for i in range(4):
        y = doc_t + s * 0.12 + i * s * 0.1
        lw = s * 0.25 if i < 3 else s * 0.15
        draw.rounded_rectangle(
            [doc_l + s * 0.05, y, doc_l + s * 0.05 + lw, y + lh],
            radius=lh // 2,
            fill=line_color,
        )

    # 麥克風（左側，白色）
    mic_cx = s * 0.32
    mic_cy = s * 0.42
    mic_w = s * 0.1
    mic_h = s * 0.18

    # 麥克風頭（圓角矩形）
    draw.rounded_rectangle(
        [mic_cx - mic_w, mic_cy - mic_h, mic_cx + mic_w, mic_cy + mic_h],
        radius=mic_w,
        fill=(255, 255, 255, 240),
    )

    # 麥克風弧線
    arc_w = s * 0.15
    arc_y = mic_cy + mic_h * 0.3
    arc_lw = max(2, int(s * 0.025))
    draw.arc(
        [mic_cx - arc_w, arc_y - s * 0.12, mic_cx + arc_w, arc_y + s * 0.12],
        start=0, end=180,
        fill=(255, 255, 255, 200),
        width=arc_lw,
    )

    # 麥克風桿
    stand_w = max(1, int(s * 0.02))
    draw.line(
        [mic_cx, arc_y + s * 0.1, mic_cx, arc_y + s * 0.2],
        fill=(255, 255, 255, 200),
        width=stand_w,
    )

    return img


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # macOS iconset 需要的尺寸
    sizes = [16, 32, 64, 128, 256, 512, 1024]

    for s in sizes:
        icon = draw_icon(s)
        # 標準解析度
        if s <= 512:
            icon.save(OUTPUT_DIR / f"icon_{s}x{s}.png")
        # Retina (@2x)
        if s >= 32:
            half = s // 2
            icon.save(OUTPUT_DIR / f"icon_{half}x{half}@2x.png")

    # 用 iconutil 轉成 .icns
    icns_path = Path(__file__).parent / "AppIcon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(OUTPUT_DIR), "-o", str(icns_path)],
        check=True,
    )

    # 清理 iconset 資料夾
    for f in OUTPUT_DIR.iterdir():
        f.unlink()
    OUTPUT_DIR.rmdir()

    print(f"圖示已產生：{icns_path}")


if __name__ == "__main__":
    main()
