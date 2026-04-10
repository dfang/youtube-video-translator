#!/usr/bin/env python3
"""
Phase 4, Step 5b: Export

Reads temp/subtitle_manifest.json.
Exports to SRT/VTT/ASS, supporting bilingual and chinese_only layouts.
Output: temp/bilingual.ass / temp/zh_only.ass (or .srt)

Supports preset styles via --preset argument or temp/subtitle_style.json.
Available presets: mobile_default, high_contrast, soft_dark, bold_yellow,
black_white_thin, black_white_medium, black_white_thick, black_white_bold,
neon_glow, warm_cream, retro_orange, mint_fresh, elegant_pink,
cinema_gold, minimal_white
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

# ---------------------------------------------------------------------------
# Preset style configurations — mirrors srt_to_ass.py PRESET_STYLES
# ---------------------------------------------------------------------------
PRESET_STYLES = {
    "mobile_default": {
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
        "font_size": 21,
        "english_font_size": 14,
        "text_color": "#0D0D0D",
        "outline_color": "#FFFFFF",
        "outline": 3.0,
        "shadow": 2.0,
        "bold": False,
        "margin_v": 18,
    },
    "neon_glow": {
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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
        "font_name": "PingFang SC Semibold",
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


def hex_to_ass_color(hex_value: str, alpha: int = 0) -> str:
    """Convert #RRGGBB to &H<alpha><BGR> (ASS color format)."""
    hex_value = hex_value.lstrip("#")
    r = int(hex_value[0:2], 16)
    g = int(hex_value[2:4], 16)
    b = int(hex_value[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def get_style_line(preset: str) -> str:
    """Build an ASS Style line for the given preset."""
    s = PRESET_STYLES.get(preset, PRESET_STYLES["mobile_default"])
    bold = -1 if s["bold"] else 0
    return (
        f"Style: Default,{s['font_name']},{s['font_size']},"
        f"{hex_to_ass_color(s['text_color'])},"
        f"{hex_to_ass_color(s['outline_color'])},"
        f"&H00000000,{bold},0,2,10,10,{s['margin_v']}"
    )


def resolve_preset(style_config: dict | None, cli_preset: str | None) -> str:
    """Resolve preset name from style_config or CLI override."""
    if cli_preset:
        return cli_preset if cli_preset in PRESET_STYLES else "mobile_default"
    if style_config:
        p = style_config.get("preset", "mobile_default")
        return p if p in PRESET_STYLES else "mobile_default"
    return "mobile_default"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def seconds_to_srt_time(secs: float) -> str:
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_ass_time(secs: float) -> str:
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    cs = int((secs - int(secs)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------------------
# Manifest loader
# ---------------------------------------------------------------------------
def load_manifest(temp_dir: Path) -> dict:
    return json.loads((temp_dir / "subtitle_manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Format exporters
# ---------------------------------------------------------------------------
def export_srt(segments: list, output_path: Path) -> int:
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = seconds_to_srt_time(seg.get("start", 0))
        end = seconds_to_srt_time(seg.get("end", 0))
        text = seg.get("translated_text", "").replace("\n", "\\N")
        lines.append(f"{i}\n{start} --> {end}\n{text}")
    output_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return 0


def export_vtt(segments: list, output_path: Path) -> int:
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = seconds_to_srt_time(seg.get("start", 0)).replace(",", ".")
        end = seconds_to_srt_time(seg.get("end", 0)).replace(",", ".")
        text = seg.get("translated_text", "").replace("\n", "\n")
        lines.append(f"{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return 0


def _build_ass_header(preset: str, title: str) -> str:
    """Build the fixed [Script Info] + [V4+ Styles] header block."""
    return f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Alignment, MarginL, MarginR, MarginV
{get_style_line(preset)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def export_ass(segments: list, output_path: Path, preset: str = "mobile_default") -> int:
    """Export manifest segments to ASS format (chinese_only layout)."""
    header = _build_ass_header(preset, "YouTube Translator")
    lines = [header]
    for seg in segments:
        start = seconds_to_ass_time(seg.get("start", 0))
        end = seconds_to_ass_time(seg.get("end", 0))
        text = seg.get("translated_text", "").replace("\n", "\\N")
        text = text.replace("{", "{{").replace("}", "}}")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return 0


def export_bilingual(segments: list, output_path: Path, preset: str = "mobile_default") -> int:
    """
    Export bilingual layout: Chinese on line 1 (large), English on line 2 (small).
    Uses \\fs tags to differentiate font sizes per line.
    """
    s = PRESET_STYLES.get(preset, PRESET_STYLES["mobile_default"])
    zh_size = s["font_size"]
    en_size = s["english_font_size"]

    header = _build_ass_header(preset, "YouTube Translator (Bilingual)")
    lines = [header]
    for seg in segments:
        src = seg.get("source_text", "").replace("\n", " ")
        dst = seg.get("translated_text", "").replace("\n", "\\N")
        # {\fs<N>} overrides font size inline; reset to en_size on line 2
        text = f"{{\\fs{zh_size}}}{dst}{{\\fs{en_size}}}\\N{{\\fs{en_size}}}{src}"
        start = seconds_to_ass_time(seg.get("start", 0))
        end = seconds_to_ass_time(seg.get("end", 0))
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Main export orchestrator
# ---------------------------------------------------------------------------
def export(
    temp_dir: Path,
    layout: str = "bilingual",
    formats: list[str] = None,
    preset: str = "mobile_default",
) -> tuple[int, dict]:
    temp_dir = Path(temp_dir)
    manifest_data = load_manifest(temp_dir)
    segments = manifest_data.get("segments", [])

    if not segments:
        return 1, {}, "subtitle_manifest.json has no segments"

    if formats is None:
        formats = ["ass"]

    # style_file wins over CLI preset
    style_file = temp_dir / "subtitle_style.json"
    if style_file.exists():
        try:
            style_config = json.loads(style_file.read_text(encoding="utf-8"))
            preset = resolve_preset(style_config, preset)
        except (json.JSONDecodeError, OSError):
            pass

    outputs = {}

    for fmt in formats:
        if layout == "bilingual":
            out_file = temp_dir / f"bilingual.{fmt}"
        elif layout == "chinese_only":
            out_file = temp_dir / f"zh_only.{fmt}"
        else:
            out_file = temp_dir / f"subtitle.{fmt}"

        if fmt == "srt":
            export_srt(segments, out_file)
        elif fmt == "vtt":
            export_vtt(segments, out_file)
        elif fmt == "ass":
            if layout == "bilingual":
                export_bilingual(segments, out_file, preset)
            else:
                export_ass(segments, out_file, preset)
        outputs[fmt] = str(out_file)
        print(f"[phase_4_export] Exported {layout} {fmt} (preset={preset}): {out_file}")

    return 0, outputs, ""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
AVAILABLE_PRESETS = list(PRESET_STYLES.keys())


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_export.py [TempDir] [Layout:bilingual|chinese_only] [Formats:srt,vtt,ass] [--preset NAME]")
        print(f"Available presets: {', '.join(AVAILABLE_PRESETS)}")
        sys.exit(1)

    temp_dir = Path(sys.argv[1])
    layout = "bilingual"
    fmt_str = "ass"
    preset = "mobile_default"

    # Parse remaining args
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--preset" and i + 1 < len(sys.argv):
            preset = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] in ("bilingual", "chinese_only"):
            layout = sys.argv[i]
            i += 1
        else:
            fmt_str = sys.argv[i]
            i += 1

    formats = fmt_str.split(",")

    exit_code, outputs, err = export(temp_dir, layout, formats, preset)
    if exit_code != 0:
        print(f"Export failed: {err}")
    else:
        print(f"Export complete: {outputs}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
