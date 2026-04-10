#!/usr/bin/env python3
"""
Phase 9: Bilibili Description Generator.
Generates a video description suitable for Bilibili based on source metadata.
"""

import sys
import json
import argparse
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from utils import get_temp_dir, get_final_dir, utc_now, shorten_text


def load_video_info(temp_dir: Path) -> dict:
    info_file = temp_dir / "video.info.json"
    if not info_file.exists():
        return {}
    try:
        return json.loads(info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_metadata(temp_dir: Path) -> dict:
    meta_file = temp_dir / "metadata.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_cover_selection(temp_dir: Path) -> dict:
    sel_file = temp_dir / "cover_selection.json"
    if not sel_file.exists():
        return {}
    try:
        return json.loads(sel_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_subtitle_manifest(temp_dir: Path) -> dict:
    manifest_file = temp_dir / "subtitle_manifest.json"
    if not manifest_file.exists():
        return {}
    try:
        return json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def generate_description(
    video_id: str,
    temp_dir: Path,
    final_dir: Path,
) -> tuple[int, str]:
    output_file = final_dir / "description.txt"
    if output_file.exists():
        return 0, str(output_file)

    info = load_video_info(temp_dir)
    meta = load_metadata(temp_dir)
    selection = load_cover_selection(temp_dir)
    manifest = load_subtitle_manifest(temp_dir)

    source_title = info.get("title") or info.get("fulltitle") or video_id
    source_url = info.get("webpage_url") or f"https://youtu.be/{video_id}"
    uploader = info.get("uploader") or info.get("channel") or "YouTube"
    duration = info.get("duration")
    description = info.get("description", "")

    # Use cover title if available, otherwise use source title
    title = selection.get("title") or source_title
    subtitle = selection.get("subtitle", "")

    # Build description sections
    lines = []

    # Title section
    lines.append(f"【{title}】")
    lines.append("")

    # Source info
    lines.append("=" * 40)
    lines.append("原始视频信息 / Original Video")
    lines.append("=" * 40)
    lines.append(f"标题: {source_title}")
    lines.append(f"频道: {uploader}")
    lines.append(f"链接: {source_url}")
    if duration:
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        if hours > 0:
            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration_str = f"{minutes}:{seconds:02d}"
        lines.append(f"时长: {duration_str}")
    lines.append("")

    # Translation note
    lines.append("=" * 40)
    lines.append("内容简介")
    lines.append("=" * 40)
    if subtitle:
        lines.append(subtitle)
        lines.append("")
    lines.append("本视频为中文本地化版本，字幕由AI翻译整理。")
    lines.append("")

    # Chapters from manifest if available
    if manifest:
        segments = manifest.get("segments", [])
        # Look for chapter markers (segments with chapter info)
        chapters = []
        for seg in segments:
            # Some manifests might have chapter info in a custom field
            if seg.get("is_chapter_start"):
                chapters.append(seg)

        if chapters and len(chapters) > 1:
            lines.append("=" * 40)
            lines.append("章节 / Chapters")
            lines.append("=" * 40)
            for i, ch in enumerate(chapters, 1):
                start_time = ch.get("start_time", 0)
                chapter_title = ch.get("text", ch.get("translated", ""))[:50]
                hours = int(start_time // 3600)
                minutes = int((start_time % 3600) // 60)
                seconds = int(start_time % 60)
                if hours > 0:
                    time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    time_str = f"{minutes}:{seconds:02d}"
                lines.append(f"{time_str} {chapter_title}")
            lines.append("")

    # Original description excerpt (first 500 chars if available)
    if description:
        lines.append("=" * 40)
        lines.append("原始简介 / Original Description")
        lines.append("=" * 40)
        # Take first 500 chars of description, truncate at line break
        desc_preview = description[:500]
        if len(description) > 500:
            desc_preview += "..."
        lines.append(desc_preview)
        lines.append("")

    # Footer
    lines.append("-" * 40)
    lines.append("搬运仅供学习交流，如有侵权请联系删除。")
    lines.append(f"生成时间: {utc_now()}")

    content = "\n".join(lines)
    output_file.write_text(content, encoding="utf-8")
    return 0, str(output_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--final-dir", required=True)
    args = parser.parse_args()

    temp = Path(args.temp_dir)
    final = Path(args.final_dir)

    exit_code, output = generate_description(args.video_id, temp, final)
    if exit_code == 0:
        print(output)
        sys.exit(0)
    else:
        print(output)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
