import json
import os
import sys

import pysubs2


def load_style_config(style_config_path=None):
    if style_config_path and os.path.exists(style_config_path):
        with open(style_config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        # 兼容旧配置：如果 JSON 里只有 preset，我们需要从这里获取样式信息
        # 现在的逻辑是：phase_7_video_muxer.py 会保证生成完整的 style.json
        return payload

    # 后备兜底配置
    return {
        "font_name": "PingFang SC Semibold",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "border_style": 1,
        "back_color": "#000000",
        "back_alpha": 255,
        "outline": 2.2,
        "shadow": 0,
        "margin_v": 18,
        "bold": False,
    }


def convert_srt_to_ass(srt_path, ass_path, style_config_path=None):
    subs = pysubs2.load(srt_path, encoding="utf-8")
    subs.info["PlayResX"] = 640
    subs.info["PlayResY"] = 360

    resolved_style = load_style_config(style_config_path)
    apply_default_style(subs, resolved_style)

    # 获取字号配置
    zh_size = resolved_style.get("font_size", 22)
    en_size = resolved_style.get("english_font_size", 16)

    for line in subs:
        raw_text = line.text.strip()
        # 匹配 phase_7_video_muxer 生成的 {\fs22} 标签
        # 或者处理普通的 \N 分隔
        if r"{\fs" in raw_text:
            # 已经是格式化好的文本，保持原样
            continue

        if r"\N" in raw_text or "\n" in raw_text:
            parts = raw_text.replace("\n", r"\N").split(r"\N")
            if len(parts) >= 2:
                zh = parts[0].strip()
                eng = parts[1].strip()
                # 重新应用层级格式
                line.text = f"{{\\fs{zh_size}}}{zh}{{\\fs{en_size}}}\\N{eng}"

    subs.sort()
    subs.save(ass_path)
    print(f"pysubs2 conversion complete: {ass_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    style_config_path = sys.argv[3] if len(sys.argv) >= 4 else None
    convert_srt_to_ass(sys.argv[1], sys.argv[2], style_config_path)
