#!/usr/bin/env python3
"""
Phase 7: Video Muxer.
Handles subtitle ASS generation (bilingual/chinese_only) and final video muxing via ffmpeg.
"""

import sys
import json
import argparse
from pathlib import Path

# Add scripts dir to path for imports
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from utils import (
    get_temp_dir,
    get_final_dir,
    run_subprocess,
    parse_srt_blocks,
    write_srt_blocks,
    target_is_fresh,
)

STYLE_CONFIG_FILENAME = "subtitle_style.json"

def get_subtitle_style_path(temp_dir: Path) -> Path:
    return temp_dir / STYLE_CONFIG_FILENAME

def build_default_subtitle_style_config() -> dict:
    return {
        "preset": "mobile_default",
        "notes": "推荐先用 mobile_default。若预览效果不好，只修改 preset，然后重新运行 phase 7 重新烧录字幕。",
        "available_presets": {
            "mobile_default": {
                "label": "移动端默认（推荐）",
                "description": "白字、黑描边、中文 18 号，适合手机竖握和横握观看。",
            },
            "high_contrast": {
                "label": "高对比",
                "description": "更粗描边、更大字号，适合亮背景或细节复杂画面。",
            },
            "soft_dark": {
                "label": "柔和暗边",
                "description": "暖白字配深灰描边，观感更柔和。",
            },
            "bold_yellow": {
                "label": "黄色强调",
                "description": "黄字深描边，适合教程、解说类内容。",
            },
            "black_white_thin": {
                "label": "黑字白描细",
                "description": "黑字配白描边（1.5px），中文 18/英文 13，适合浅色背景。",
            },
            "black_white_medium": {
                "label": "黑字白描中",
                "description": "黑字配白描边（2.5px），中文 20/英文 14，中等醒目。",
            },
            "black_white_thick": {
                "label": "黑字白描粗",
                "description": "黑字配白描边（3.5px），中文 22/英文 15，粗壮有力。",
            },
            "black_white_bold": {
                "label": "黑字白描强调",
                "description": "深黑字配白描边（3.0px）+白底阴影，中文 21/英文 14。",
            },
        },
    }

def ensure_subtitle_style_config(temp_dir: Path) -> Path:
    style_path = get_subtitle_style_path(temp_dir)
    if not style_path.exists():
        style_path.write_text(
            json.dumps(build_default_subtitle_style_config(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return style_path

def ensure_chinese_ass(temp_dir: Path) -> tuple[int, str]:
    zh_translated = temp_dir / "zh_translated.srt"
    zh_only_ass = temp_dir / "zh_only.ass"
    style_config = ensure_subtitle_style_config(temp_dir)

    if target_is_fresh(zh_only_ass, [zh_translated, style_config, SKILL_ROOT / "scripts" / "srt_to_ass.py"]):
        return 0, str(zh_only_ass)
    if not zh_translated.exists():
        return 1, "zh_translated.srt not found"

    exit_code, output = run_subprocess(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/srt_to_ass.py"),
            str(zh_translated),
            str(zh_only_ass),
            str(style_config),
        ]
    )
    if exit_code != 0:
        return exit_code, output
    if not zh_only_ass.exists():
        return 1, "zh_only.ass not generated"
    return 0, str(zh_only_ass)

def ensure_bilingual_ass(temp_dir: Path) -> tuple[int, str]:
    zh_translated = temp_dir / "zh_translated.srt"
    en_audited = temp_dir / "en_audited.srt"
    bilingual_srt = temp_dir / "bilingual.srt"
    bilingual_ass = temp_dir / "bilingual.ass"
    style_config = ensure_subtitle_style_config(temp_dir)

    if target_is_fresh(
        bilingual_ass,
        [zh_translated, en_audited, style_config, SKILL_ROOT / "scripts" / "srt_to_ass.py"],
    ):
        return 0, str(bilingual_ass)

    if not zh_translated.exists():
        return 1, "zh_translated.srt not found"
    if not en_audited.exists():
        return 1, "en_audited.srt not found"

    zh_blocks = parse_srt_blocks(zh_translated)
    en_blocks = parse_srt_blocks(en_audited)
    if len(zh_blocks) != len(en_blocks):
        return 1, f"bilingual subtitle mismatch: zh={len(zh_blocks)} en={len(en_blocks)}"

    merged = []
    for zh_block, en_block in zip(zh_blocks, en_blocks):
        if zh_block["index"] != en_block["index"] or zh_block["timecode"] != en_block["timecode"]:
            return 1, f"bilingual subtitle mismatch at block {zh_block['index']}"
        zh_text = zh_block["text"].replace("\\N", "\n").strip()
        en_text = en_block["text"].replace("\\N", "\n").strip()
        merged.append(
            {
                "index": zh_block["index"],
                "timecode": zh_block["timecode"],
                "text": f"{zh_text}\n{en_text}".strip(),
            }
        )

    write_srt_blocks(bilingual_srt, merged)
    exit_code, output = run_subprocess(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/srt_to_ass.py"),
            str(bilingual_srt),
            str(bilingual_ass),
            str(style_config),
        ]
    )
    if exit_code != 0:
        return exit_code, output
    if not bilingual_ass.exists():
        return 1, "bilingual.ass not generated"
    return 0, str(bilingual_ass)

def ensure_subtitle_overlay(temp_dir: Path, layout: str = "bilingual") -> tuple[int, str]:
    overlay = temp_dir / "subtitle_overlay.ass"

    if layout == "chinese_only":
        exit_code, source_ass = ensure_chinese_ass(temp_dir)
    else:
        exit_code, source_ass = ensure_bilingual_ass(temp_dir)

    if exit_code != 0:
        return exit_code, source_ass

    source_path = Path(source_ass)
    if not target_is_fresh(overlay, [source_path]):
        overlay.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return 0, str(overlay)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--final-dir", required=True)
    parser.add_argument("--layout", default="bilingual")
    parser.add_argument("--original-audio", action="store_true")
    args = parser.parse_args()

    temp = Path(args.temp_dir)
    final = Path(args.final_dir)
    video = temp / "raw_video.mp4"
    voiceover = temp / "zh_voiceover.mp3"
    final_video = final / "final_video.mp4"

    if not video.exists():
        print(f"Error: raw_video.mp4 not found in {temp}")
        sys.exit(1)

    # 1. Prepare subtitles
    exit_code, message = ensure_subtitle_overlay(temp, args.layout)
    if exit_code != 0:
        print(f"Error preparing subtitles: {message}")
        sys.exit(exit_code)
    
    ass = Path(message)

    # 2. Check freshness
    freshness_sources = [video, ass]
    if voiceover.exists() and not args.original_audio:
        freshness_sources.append(voiceover)
    
    if final_video.exists() and target_is_fresh(final_video, freshness_sources):
        print(f"SKIP: final_video.mp4 is up to date.")
        sys.exit(0)

    # 3. Muxing
    audio_arg = str(voiceover) if (voiceover.exists() and not args.original_audio) else ""
    cmd = [
        sys.executable, str(SKILL_ROOT / "scripts/video_muxer.py"),
        str(video), audio_arg, str(ass), str(final),
    ]
    if args.original_audio or not voiceover.exists():
        cmd.append("--original-audio")

    exit_code, output = run_subprocess(
        cmd,
        heartbeat_phase=7,
        heartbeat_name="Video Muxing",
    )
    if exit_code == 0 and final_video.exists():
        print(str(final_video))
        sys.exit(0)
    else:
        print(output)
        sys.exit(exit_code if exit_code != 0 else 1)

if __name__ == "__main__":
    main()
