"""
图片处理工具 — 照片预处理、缩放、格式转换。
提取自原项目：tools/ai_api.py (resize_image_for_api) + tools/generate.py (compress_image)
"""

from __future__ import annotations

import io
from PIL import Image as PILImage, ImageOps


def preprocess_for_vlm(image_path: str, max_size: int = 1024, quality: int = 80) -> bytes:
    """
    将图片预处理为适合 VLM API 的 JPEG bytes。
    提取自原项目 tools/ai_api.py — resize_image_for_api()。

    - 自动旋转 EXIF 方向
    - 透明图补白底
    - 等比缩放到 max_size px
    - 输出 JPEG bytes
    """
    img = PILImage.open(image_path)
    img = ImageOps.exif_transpose(img)

    # 处理透明/调色板模式
    if img.mode in ('RGBA', 'P', 'LA'):
        rgb = PILImage.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = rgb
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # 等比缩放
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def compress_for_seedream(image_path: str, max_size: int = 1024, quality: int = 70) -> str:
    """
    压缩图片为 Seedream API 用的 base64 data URI。
    提取自原项目 tools/generate.py — compress_image()。

    - 透明 PNG 在中性灰背景上合成
    - 等比缩放
    - 返回 data:image/jpeg;base64,... 格式
    """
    import base64
    NEUTRAL_GRAY = (217, 217, 217)

    img = PILImage.open(image_path)
    # 处理透明通道
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        bg = PILImage.new('RGB', img.size, NEUTRAL_GRAY)
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    w, h = img.size
    if w > max_size or h > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f'data:image/jpeg;base64,{b64}'


def check_photo_quality(image_path: str) -> dict:
    """
    快速检测照片质量，用于拍照前预检。
    返回: {"ok": bool, "issues": [str]}
    """
    issues = []
    try:
        img = PILImage.open(image_path)
        w, h = img.size

        if min(w, h) < 400:
            issues.append("分辨率过低（建议至少 800px）")
        if max(w, h) < 600:
            issues.append("照片太小，可能无法准确分析")

        # 粗略亮度检测
        gray = img.convert('L')
        pixels = list(gray.getdata())
        avg_brightness = sum(pixels) / len(pixels)
        if avg_brightness < 30:
            issues.append("光线太暗，建议在明亮处拍摄")
        if avg_brightness > 240:
            issues.append("画面过曝，避免强光直射")

    except Exception as e:
        issues.append(f"无法读取照片: {e}")

    return {"ok": len(issues) == 0, "issues": issues}
