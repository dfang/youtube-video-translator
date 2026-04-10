#!/usr/bin/env python3
"""
Phase 4, Step 5b: Export

Reads temp/subtitle_manifest.json.
Exports to SRT/VTT/ASS, supporting bilingual and chinese_only layouts.
Output: temp/bilingual.ass / temp/zh_only.ass (or .srt)
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


def seconds_to_srt_time(secs: float) -> str:
    """Convert float seconds to SRT timestamp: 00:00:00,000"""
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_manifest(temp_dir: Path) -> dict:
    return json.loads((temp_dir / "subtitle_manifest.json").read_text(encoding="utf-8"))


def export_srt(segments: list, output_path: Path) -> int:
    """Export manifest segments to SRT format."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = seconds_to_srt_time(seg.get("start", 0))
        end = seconds_to_srt_time(seg.get("end", 0))
        text = seg.get("translated_text", "").replace("\n", "\\N")
        lines.append(f"{i}\n{start} --> {end}\n{text}")
    output_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return 0


def export_vtt(segments: list, output_path: Path) -> int:
    """Export manifest segments to VTT format."""
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = seconds_to_srt_time(seg.get("start", 0)).replace(",", ".")
        end = seconds_to_srt_time(seg.get("end", 0)).replace(",", ".")
        text = seg.get("translated_text", "").replace("\n", "\n")
        lines.append(f"{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return 0


def export_ass(segments: list, output_path: Path, style_config: dict | None = None) -> int:
    """
    Export manifest segments to ASS format.
    Uses hardcoded default style (matching mobile_default preset).
    """
    default_style = {
        "PlayResX": 1920,
        "PlayResY": 1080,
        "Fontname": "Arial",
        "Fontsize": "36",
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H00000000",
        "Bold": "0",
        "Italic": "0",
        "Alignment": "2",
        "MarginL": 10,
        "MarginR": 10,
        "MarginV": 10,
    }
    if style_config:
        preset = style_config.get("preset", "mobile_default")
        notes = style_config.get("notes", "")
        if style_config.get("available_presets", {}).get(preset):
            # Use preset config if available
            pass

    header = f"""[Script Info]
Title: YouTube Translator
ScriptType: v4.00+
PlayResX: {default_style['PlayResX']}
PlayResY: {default_style['PlayResY']}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Alignment, MarginL, MarginR, MarginV
Style: Default,{default_style['Fontname']},{default_style['Fontsize']},{default_style['PrimaryColour']},{default_style['OutlineColour']},{default_style['BackColour']},{default_style['Bold']},{default_style['Italic']},{default_style['Alignment']},{default_style['MarginL']},{default_style['MarginR']},{default_style['MarginV']}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    for seg in segments:
        start = seconds_to_ass_time(seg.get("start", 0))
        end = seconds_to_ass_time(seg.get("end", 0))
        text = seg.get("translated_text", "").replace("\n", "\\N")
        # Escape braces
        text = text.replace("{", "{{").replace("}", "}}")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return 0


def seconds_to_ass_time(secs: float) -> str:
    """Convert float seconds to ASS timestamp: H:MM:SS.CC"""
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    cs = int((secs - int(secs)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def export_bilingual(segments: list, output_path: Path, style_config: dict | None = None) -> int:
    """
    Export bilingual layout: source_text on line 1, translated_text on line 2.
    """
    lines = []
    for seg in segments:
        src = seg.get("source_text", "").replace("\n", " ")
        dst = seg.get("translated_text", "").replace("\n", "\\N")
        text = f"{src}\\N{dst}"
        start = seconds_to_ass_time(seg.get("start", 0))
        end = seconds_to_ass_time(seg.get("end", 0))
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    header = f"""[Script Info]
Title: YouTube Translator (Bilingual)
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Alignment, MarginL, MarginR, MarginV
Style: Default,Arial,36,&H00FFFFFF,&H00000000,&H00000000,0,0,2,10,10,10

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    output_path.write_text(header + "\n".join(lines), encoding="utf-8")
    return 0


def export(
    temp_dir: Path,
    layout: str = "bilingual",
    formats: list[str] = None,
) -> tuple[int, dict]:
    temp_dir = Path(temp_dir)
    manifest_data = load_manifest(temp_dir)
    segments = manifest_data.get("segments", [])

    if not segments:
        return 1, {}, "subtitle_manifest.json has no segments"

    if formats is None:
        formats = ["ass"]  # default to ASS

    style_file = temp_dir / "subtitle_style.json"
    style_config = None
    if style_file.exists():
        try:
            style_config = json.loads(style_file.read_text(encoding="utf-8"))
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
                export_bilingual(segments, out_file, style_config)
            else:
                export_ass(segments, out_file, style_config)
        outputs[fmt] = str(out_file)
        print(f"[phase_4_export] Exported {layout} {fmt}: {out_file}")

    return 0, outputs, ""


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_export.py [TempDir] [Layout:bilingual|chinese_only] [Formats:srt,vtt,ass]")
        sys.exit(1)

    temp_dir = Path(sys.argv[1])
    layout = sys.argv[2] if len(sys.argv) > 2 else "bilingual"
    fmt_str = sys.argv[3] if len(sys.argv) > 3 else "ass"
    formats = fmt_str.split(",")

    exit_code, outputs, err = export(temp_dir, layout, formats)
    if exit_code != 0:
        print(f"Export failed: {err}")
    else:
        print(f"Export complete: {outputs}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
