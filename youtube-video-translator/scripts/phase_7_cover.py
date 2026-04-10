#!/usr/bin/env python3
"""
Phase 6: Cover Generator.
Handles cover title/subtitle options, interactive selection, and image generation.
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
    utc_now,
    dedupe_preserve_order,
    shorten_text,
    get_ffmpeg_path,
)

def load_video_info(temp_dir: Path) -> dict:
    info_file = temp_dir / "video.info.json"
    if not info_file.exists():
        return {}
    try:
        return json.loads(info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

def build_cover_options(video_id: str, temp_dir: Path, layout: str = "bilingual") -> dict:
    info = load_video_info(temp_dir)
    source_title = (
        info.get("title")
        or info.get("fulltitle")
        or video_id
    )
    source_title = shorten_text(source_title, 58)
    uploader = shorten_text(info.get("uploader") or info.get("channel") or "YouTube", 36)
    layout_label = "双语字幕" if layout == "bilingual" else "中文字幕"

    title_candidates = dedupe_preserve_order(
        [
            f"{layout_label} | {source_title}",
            f"{source_title}：{layout_label}版",
            f"中文解说 | {source_title}",
            f"{source_title}｜完整中文翻译",
            f"{source_title}｜中文搬运",
        ]
    )[:5]

    subtitle_candidates = dedupe_preserve_order(
        [
            f"来源：{uploader}",
            layout_label,
            f"{layout_label} / 原作者信息见简介",
            "中文本地化版本",
            "转载与翻译整理",
        ]
    )

    candidates = []
    for idx, title in enumerate(title_candidates, start=1):
        subtitle = subtitle_candidates[(idx - 1) % len(subtitle_candidates)]
        candidates.append(
            {
                "id": idx,
                "title": shorten_text(title, 80),
                "subtitle": shorten_text(subtitle, 40),
            }
        )

    return {
        "video_id": video_id,
        "generated_at": utc_now(),
        "source_title": source_title,
        "subtitle_layout": layout,
        "candidates": candidates,
        "selection_template": {
            "candidate_id": 1,
            "title": "optional custom title",
            "subtitle": "optional custom subtitle",
            "background_image": "optional absolute or relative image path",
        },
    }

def resolve_cover_selection(temp_dir: Path, options: dict) -> tuple[bool, dict | None, str]:
    selection_file = temp_dir / "cover_selection.json"
    if not selection_file.exists():
        return False, None, f"interactive: choose title and write {selection_file}"

    try:
        selection = json.loads(selection_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None, f"interactive: invalid JSON in {selection_file}"

    if not isinstance(selection, dict):
        return False, None, f"interactive: {selection_file} must contain a JSON object"

    title = (selection.get("title") or "").strip()
    subtitle = (selection.get("subtitle") or "").strip()
    candidate_id = selection.get("candidate_id")

    candidate_map = {item["id"]: item for item in options.get("candidates", [])}
    if candidate_id is not None:
        if not isinstance(candidate_id, int) or candidate_id not in candidate_map:
            return False, None, f"interactive: candidate_id must match cover_options.json"
        candidate = candidate_map[candidate_id]
        title = title or candidate["title"]
        subtitle = subtitle or candidate["subtitle"]

    if not title:
        return False, None, f"interactive: title is required in {selection_file}"
    if not subtitle:
        return False, None, f"interactive: subtitle is required in {selection_file}"

    background_image = (selection.get("background_image") or "").strip()
    if background_image:
        bg_path = Path(background_image)
        if not bg_path.is_absolute():
            bg_path = (Path.cwd() / bg_path).resolve()
        if not bg_path.exists():
            return False, None, f"interactive: background image not found: {bg_path}"
        background_image = str(bg_path)

    return True, {
        "title": shorten_text(title, 80),
        "subtitle": shorten_text(subtitle, 40),
        "background_image": background_image,
    }, ""

def ensure_cover_background(temp_dir: Path) -> tuple[int, str]:
    existing = temp_dir / "cover_bg.jpg"
    if existing.exists():
        return 0, str(existing)

    raw_video = temp_dir / "raw_video.mp4"
    if not raw_video.exists():
        return 1, "raw_video.mp4 not found for cover background extraction"

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return 1, "FFmpeg not found"

    commands = [
        [ffmpeg, "-y", "-ss", "00:00:05", "-i", str(raw_video), "-frames:v", "1", str(existing)],
        [ffmpeg, "-y", "-i", str(raw_video), "-frames:v", "1", str(existing)],
    ]
    output = ""
    for cmd in commands:
        exit_code, output = run_subprocess(cmd, heartbeat_phase=6, heartbeat_name="Cover Background Extraction")
        if exit_code == 0 and existing.exists():
            return 0, str(existing)
    return 1, output or "cover background extraction failed"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--final-dir", required=True)
    parser.add_argument("--layout", default="bilingual")
    args = parser.parse_args()

    temp = Path(args.temp_dir)
    final = Path(args.final_dir)
    cover = final / "cover_final.jpg"

    if cover.exists():
        print(str(cover))
        sys.exit(0)

    options_file = temp / "cover_options.json"
    if not options_file.exists():
        options = build_cover_options(args.video_id, temp, args.layout)
        options_file.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"WAIT: choose cover options in {options_file}")
        sys.exit(0)
    else:
        try:
            options = json.loads(options_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            options = build_cover_options(args.video_id, temp, args.layout)
            options_file.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")

    valid, selection, message = resolve_cover_selection(temp, options)
    if not valid:
        print(message)
        sys.exit(0) # In runner, we treat 'interactive' as WAITING

    background_image = selection["background_image"]
    if background_image:
        bg_path = Path(background_image)
    else:
        exit_code, bg_message = ensure_cover_background(temp)
        if exit_code != 0:
            print(f"Error extracting cover background: {bg_message}")
            sys.exit(exit_code)
        bg_path = Path(bg_message)

    exit_code, output = run_subprocess(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts/cover_generator.py"),
            str(bg_path),
            str(cover),
            selection["title"],
            selection["subtitle"],
        ]
    )
    if exit_code == 0 and cover.exists():
        print(str(cover))
        sys.exit(0)
    else:
        print(output or "cover generation failed")
        sys.exit(exit_code if exit_code != 0 else 1)

if __name__ == "__main__":
    main()
