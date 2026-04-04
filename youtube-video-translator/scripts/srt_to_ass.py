import json
import os
import sys

import pysubs2


STYLE_PRESETS = {
    "mobile_default": {
        "label": "移动端默认",
        "font_name": "PingFang SC Semibold",
        "font_size": 18,
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "border_style": 1,
        "back_color": "#000000",
        "back_alpha": 255,
        "outline": 2.2,
        "shadow": 0,
        "margin_v": 18,
        "english_font_size": 14,
        "bold": False,
    },
    "high_contrast": {
        "label": "高对比",
        "font_name": "PingFang SC Semibold",
        "font_size": 20,
        "text_color": "#FFFFFF",
        "outline_color": "#000000",
        "border_style": 3,
        "back_color": "#000000",
        "back_alpha": 110,
        "outline": 3.0,
        "shadow": 0,
        "margin_v": 18,
        "english_font_size": 15,
        "bold": True,
    },
    "soft_dark": {
        "label": "柔和暗边",
        "font_name": "PingFang SC",
        "font_size": 18,
        "text_color": "#FFF7E8",
        "outline_color": "#1A1A1A",
        "border_style": 1,
        "back_color": "#000000",
        "back_alpha": 255,
        "outline": 2.4,
        "shadow": 0,
        "margin_v": 20,
        "english_font_size": 14,
        "bold": False,
    },
    "bold_yellow": {
        "label": "黄色强调",
        "font_name": "PingFang SC Semibold",
        "font_size": 19,
        "text_color": "#FFE45C",
        "outline_color": "#111111",
        "border_style": 1,
        "back_color": "#000000",
        "back_alpha": 255,
        "outline": 2.6,
        "shadow": 0,
        "margin_v": 18,
        "english_font_size": 14,
        "bold": True,
    },
}

DEFAULT_PRESET = "mobile_default"


def hex_to_color(hex_value, alpha=0):
    value = hex_value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid color value: {hex_value}")
    return pysubs2.Color(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), a=int(alpha))


def load_style_config(style_config_path=None):
    preset_name = DEFAULT_PRESET
    overrides = {}

    if style_config_path and os.path.exists(style_config_path):
        with open(style_config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            requested = payload.get("preset")
            if requested in STYLE_PRESETS:
                preset_name = requested
            overrides = {
                "font_name": payload.get("font_name"),
                "font_size": payload.get("font_size"),
                "text_color": payload.get("text_color"),
                "outline_color": payload.get("outline_color"),
                "border_style": payload.get("border_style"),
                "back_color": payload.get("back_color"),
                "back_alpha": payload.get("back_alpha"),
                "outline": payload.get("outline"),
                "shadow": payload.get("shadow"),
                "margin_v": payload.get("margin_v"),
                "english_font_size": payload.get("english_font_size"),
                "bold": payload.get("bold"),
            }

    resolved = dict(STYLE_PRESETS[preset_name])
    for key, value in overrides.items():
        if value is not None:
            resolved[key] = value
    resolved["preset"] = preset_name
    return resolved


def apply_default_style(subs, resolved_style):
    style = pysubs2.SSAStyle()
    style.fontname = resolved_style["font_name"]
    style.fontsize = resolved_style["font_size"]
    style.primarycolor = hex_to_color(resolved_style["text_color"])
    style.outlinecolor = hex_to_color(resolved_style["outline_color"])
    style.borderstyle = int(resolved_style["border_style"])
    style.backcolor = hex_to_color(
        resolved_style["back_color"],
        alpha=resolved_style["back_alpha"],
    )
    style.outline = float(resolved_style["outline"])
    style.shadow = float(resolved_style["shadow"])
    style.bold = bool(resolved_style["bold"])
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    style.marginv = int(resolved_style["margin_v"])
    subs.styles["Default"] = style


def convert_srt_to_ass(srt_path, ass_path, style_config_path=None):
    subs = pysubs2.load(srt_path, encoding="utf-8")
    subs.info["PlayResX"] = 640
    subs.info["PlayResY"] = 360

    resolved_style = load_style_config(style_config_path)
    apply_default_style(subs, resolved_style)
    english_font_size = int(resolved_style["english_font_size"])

    for line in subs:
        raw_text = line.text.strip()
        if r"\N" in raw_text:
            parts = raw_text.split(r"\N")
            if len(parts) >= 2:
                zh = parts[0].strip()
                eng = parts[1].strip()
                line.text = f"{zh}\\N{{\\fs{english_font_size}}}{eng}"
        elif "\n" in raw_text:
            parts = raw_text.split("\n")
            if len(parts) >= 2:
                zh = parts[0].strip()
                eng = parts[1].strip()
                line.text = f"{zh}\\N{{\\fs{english_font_size}}}{eng}"

    subs.sort()
    subs.save(ass_path)
    print(
        f"pysubs2 conversion complete: {ass_path} "
        f"(preset={resolved_style['preset']}, font={resolved_style['font_size']})"
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    style_config_path = sys.argv[3] if len(sys.argv) >= 4 else None
    convert_srt_to_ass(sys.argv[1], sys.argv[2], style_config_path)
