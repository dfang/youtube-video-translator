import json
import os
import sys
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

import pysubs2

# 预设样式配置表
PRESET_STYLES = {
    "mobile_default": {
        "label": "移动端默认（推荐）",
        "description": "白字、黑描边、中文 18，适合手机竖横握观看。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline": 2.2,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "high_contrast": {
        "label": "高对比",
        "description": "更粗描边、更大字号，适合亮背景或复杂画面。",
        "font_name": "STHeiti",
        "font_size": 22,
        "english_font_size": 16,
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline": 3.5,
        "shadow": 0,
        "bold": True,
        "margin_v": 20,
    },
    "soft_dark": {
        "label": "柔和暗边",
        "description": "暖白字配深灰描边，观感更柔和。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFF8E8",
        "outline_color": "#333333",
        "outline": 2.0,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "bold_yellow": {
        "label": "黄色强调",
        "description": "黄字深描边，适合教程、解说类内容。",
        "font_name": "STHeiti",
        "font_size": 20,
        "english_font_size": 15,
        "text_color": "#FFD700",
        "outline_color": "#1A1A1A",
        "outline": 2.5,
        "shadow": 0,
        "bold": True,
        "margin_v": 18,
    },
    "black_white_thin": {
        "label": "黑字白描细",
        "description": "黑字配白描边（1.5px），中文 18/英文 13，适合浅色背景。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 13,
        "text_color": "#1A1A1A",
        "outline_color": "#FFFFFF",
        "outline": 1.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "black_white_medium": {
        "label": "黑字白描中",
        "description": "黑字配白描边（2.5px），中文 20/英文 14，中等醒目。",
        "font_name": "STHeiti",
        "font_size": 20,
        "english_font_size": 14,
        "text_color": "#1A1A1A",
        "outline_color": "#FFFFFF",
        "outline": 2.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "black_white_thick": {
        "label": "黑字白描粗",
        "description": "黑字配白描边（3.5px），中文 22/英文 15，粗壮有力。",
        "font_name": "STHeiti",
        "font_size": 22,
        "english_font_size": 15,
        "text_color": "#1A1A1A",
        "outline_color": "#FFFFFF",
        "outline": 3.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 20,
    },
    "black_white_bold": {
        "label": "黑字白描强调",
        "description": "深黑字配白描边（3.0px）+白底阴影，中文 21/英文 14。",
        "font_name": "STHeiti",
        "font_size": 21,
        "english_font_size": 14,
        "text_color": "#0D0D0D",
        "outline_color": "#FFFFFF",
        "outline": 3.0,
        "shadow": 2.0,
        "bold": False,
        "margin_v": 18,
    },
    # 新增样式
    "neon_glow": {
        "label": "霓虹发光",
        "description": "亮青字配深色外发光，科幻感十足。",
        "font_name": "STHeiti",
        "font_size": 20,
        "english_font_size": 14,
        "text_color": "#00FFFF",
        "outline_color": "#003333",
        "outline": 3.0,
        "shadow": 4.0,
        "bold": False,
        "margin_v": 18,
    },
    "warm_cream": {
        "label": "暖色奶油",
        "description": "奶油白字配棕色描边，温馨复古感。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFF5E6",
        "outline_color": "#8B4513",
        "outline": 2.0,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "retro_orange": {
        "label": "复古橙色",
        "description": "橙色文字配深棕描边，电影感强。",
        "font_name": "STHeiti",
        "font_size": 20,
        "english_font_size": 14,
        "text_color": "#FF8C00",
        "outline_color": "#3D2006",
        "outline": 2.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "mint_fresh": {
        "label": "薄荷清新",
        "description": "薄荷绿字配深绿描边，清爽舒适。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#98FB98",
        "outline_color": "#006400",
        "outline": 2.0,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "elegant_pink": {
        "label": "优雅粉紫",
        "description": "浅粉紫字配深紫描边，柔美风格。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFB6C1",
        "outline_color": "#4A0E2E",
        "outline": 2.0,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "cinema_gold": {
        "label": "影院金标",
        "description": "金色字配深棕描边，影院字幕经典风格。",
        "font_name": "STHeiti",
        "font_size": 20,
        "english_font_size": 14,
        "text_color": "#DAA520",
        "outline_color": "#2D1B00",
        "outline": 2.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
    "minimal_white": {
        "label": "极简白字",
        "description": "纯白字几乎无描边，极简主义风格。",
        "font_name": "STHeiti",
        "font_size": 18,
        "english_font_size": 14,
        "text_color": "#FFFFFF",
        "outline_color": "#CCCCCC",
        "outline": 0.5,
        "shadow": 0,
        "bold": False,
        "margin_v": 18,
    },
}


def load_style_config(style_config_path=None):
    if style_config_path and os.path.exists(style_config_path):
        with open(style_config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        # 根据 preset 名称加载对应的样式参数
        preset_name = payload.get("preset", "mobile_default")
        preset_styles = PRESET_STYLES.get(preset_name, PRESET_STYLES["mobile_default"])
        # 合并：payload 里的参数优先级更高（允许用户覆盖部分设置）
        return {**preset_styles, **payload}
    return PRESET_STYLES["mobile_default"]

def hex_to_color(hex_value, alpha=0):
    value = hex_value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid color value: {hex_value}")
    return pysubs2.Color(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), a=int(alpha))

def apply_default_style(subs, resolved_style):
    style = pysubs2.SSAStyle()
    style.fontname = resolved_style.get("font_name", "STHeiti")
    style.fontsize = resolved_style.get("font_size", 18)
    style.primarycolor = hex_to_color(resolved_style.get("text_color", "#FFFFFF"))
    style.outlinecolor = hex_to_color(resolved_style.get("outline_color", "#000000"))
    style.borderstyle = int(resolved_style.get("border_style", 1))
    style.backcolor = hex_to_color(
        resolved_style.get("back_color", "#000000"),
        alpha=resolved_style.get("back_alpha", 255),
    )
    style.outline = float(resolved_style.get("outline", 2.2))
    style.shadow = float(resolved_style.get("shadow", 0))
    style.bold = bool(resolved_style.get("bold", False))
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    style.marginv = int(resolved_style.get("margin_v", 18))
    subs.styles["Default"] = style


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
