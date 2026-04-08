#!/usr/bin/env python3
"""
Unified phase runner for youtube-video-translator.
Handles phase ordering, checkpointing, and resumable execution.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent
# Always use the actual location of the running script.
# When OpenClaw invokes the installed skill, __file__.resolve() already points there.
SKILL_ROOT = _dev_root

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from state_manager import get_state_path, load_state, update_phase, is_phase_completed, get_next_pending_phase, PHASE_NAMES
from utils import (
    get_ffmpeg_path,
    get_video_dir,
    get_temp_dir,
    get_final_dir,
    ensure_dirs,
    run_subprocess,
    utc_now,
    parse_srt_blocks,
    _seconds_to_srt,
    write_srt_blocks,
    target_is_fresh,
    dedupe_preserve_order,
    shorten_text,
)


INTENT_ENUMS = {
    "audio_mode": {"original", "voiceover"},
    "subtitle_mode": {"auto", "official_only", "transcribe"},
    "subtitle_layout": {"bilingual", "chinese_only"},
}

STYLE_CONFIG_FILENAME = "subtitle_style.json"


def ensure_mise_environment():
    """Programmatically activate mise for the current process and children."""
    try:
        # Check if mise is available
        if not shutil.which("mise"):
            return

        # Get mise environment in JSON format
        result = subprocess.run(
            ["mise", "env", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return

        mise_env = json.loads(result.stdout)
        # Update current environment
        for key, value in mise_env.items():
            os.environ[key] = value

        # Update sys.path if necessary? (usually not needed if we use sys.executable)
        # But we report it to show it worked.
        if "PATH" in mise_env:
            os.environ["PATH"] = mise_env["PATH"]

    except Exception:
        # Silently fail if mise is missing or errors (fallback to system env)
        pass


def report_step(phase: int, step: str, status: str, msg: str = "") -> None:
    if status == "RUNNING":
        print(f"[Phase {phase}/10][STEP][RUNNING] {step}")
    elif status == "DONE":
        line = f"[Phase {phase}/10][STEP][DONE] {step}"
        if msg:
            line += f" | {msg}"
        print(line)
    elif status == "FAILED":
        line = f"[Phase {phase}/10][STEP][FAILED] {step}"
        if msg:
            line += f" | error: {msg}"
        print(line)


def validate_intent_payload(intent: dict) -> tuple[bool, str]:
    if not isinstance(intent, dict):
        return False, "intent.json must be a JSON object"

    for field, allowed in INTENT_ENUMS.items():
        value = intent.get(field)
        if value not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            return False, f"{field} must be one of: {allowed_values}"

    for field in ("publish", "cleanup", "confirmed"):
        if not isinstance(intent.get(field), bool):
            return False, f"{field} must be true or false"

    if not intent.get("confirmed"):
        return False, "confirmed must be true before continuing"

    return True, ""


def is_valid_youtube_url(url: str) -> bool:
    return "youtube.com/" in url or "youtu.be/" in url


def find_existing_official_srt(temp_dir: Path) -> Path | None:
    patterns = ("en_official*.srt", "*.en*.srt", "*English*.srt")
    for pattern in patterns:
        matches = sorted(
            candidate for candidate in temp_dir.glob(pattern)
            if candidate.is_file() and candidate.name != "en_original.srt"
        )
        if matches:
            return matches[0]
    return None


def ensure_source_subtitles(temp_dir: Path, intent: dict | None = None) -> tuple[int, str]:
    en_original = temp_dir / "en_original.srt"
    if en_original.exists():
        return 0, str(en_original)

    subtitle_mode = (intent or {}).get("subtitle_mode", "auto")
    official = find_existing_official_srt(temp_dir)
    if subtitle_mode == "official_only":
        if not official:
            return 1, "official subtitles required but not found"
        en_original.write_text(official.read_text(encoding="utf-8"), encoding="utf-8")
        return 0, str(en_original)
    if subtitle_mode != "transcribe" and official:
        en_original.write_text(official.read_text(encoding="utf-8"), encoding="utf-8")
        return 0, str(en_original)

    raw_video = temp_dir / "raw_video.mp4"
    if not raw_video.exists():
        return 1, "raw_video.mp4 not found"

    exit_code, output = run_subprocess(
        [sys.executable, str(SKILL_ROOT / "scripts/whisperx_transcriber.py"), str(raw_video), str(temp_dir)],
        heartbeat_phase=4,
        heartbeat_name=PHASE_NAMES[4],
    )
    if exit_code != 0:
        return exit_code, output
    if not en_original.exists():
        return 1, "en_original.srt not generated"
    return 0, str(en_original)


def ensure_audited_subtitles(temp_dir: Path) -> tuple[int, str]:
    en_original = temp_dir / "en_original.srt"
    en_audited = temp_dir / "en_audited.srt"
    compat_audited = temp_dir / "en_original_audited.srt"

    if en_audited.exists():
        if not compat_audited.exists():
            compat_audited.write_text(en_audited.read_text(encoding="utf-8"), encoding="utf-8")
        return 0, str(en_audited)

    if compat_audited.exists():
        en_audited.write_text(compat_audited.read_text(encoding="utf-8"), encoding="utf-8")
        return 0, str(en_audited)

    if not en_original.exists():
        return 1, "en_original.srt not found"

    exit_code, output = run_subprocess(
        [sys.executable, str(SKILL_ROOT / "scripts/subtitle_splitter.py"), str(en_original), str(en_audited)]
    )
    if exit_code != 0:
        return exit_code, output
    compat_audited.write_text(en_audited.read_text(encoding="utf-8"), encoding="utf-8")
    return 0, str(en_audited)


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


def ensure_subtitle_overlay(temp_dir: Path, intent: dict | None = None) -> tuple[int, str]:
    layout = (intent or {}).get("subtitle_layout", "bilingual")
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


def load_video_info(temp_dir: Path) -> dict:
    info_file = temp_dir / "video.info.json"
    if not info_file.exists():
        return {}
    try:
        return json.loads(info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_cover_options(video_id: str, temp_dir: Path, intent: dict | None = None) -> dict:
    info = load_video_info(temp_dir)
    source_title = (
        info.get("title")
        or info.get("fulltitle")
        or video_id
    )
    source_title = shorten_text(source_title, 58)
    uploader = shorten_text(info.get("uploader") or info.get("channel") or "YouTube", 36)
    layout = (intent or {}).get("subtitle_layout", "bilingual")
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
        exit_code, output = run_subprocess(cmd, heartbeat_phase=6, heartbeat_name=PHASE_NAMES[6])
        if exit_code == 0 and existing.exists():
            return 0, str(existing)
    return 1, output or "cover background extraction failed"


def run_phase_command(phase: int, video_id: str, intent: dict | None = None) -> tuple[str, str]:
    temp = get_temp_dir(video_id)
    final = get_final_dir(video_id)

    if phase == 0:
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/env_check.py")],
            heartbeat_phase=0,
            heartbeat_name=PHASE_NAMES[0],
        )
        return ("done", output) if exit_code == 0 else ("failed", output)

    if phase == 1:
        intent_file = temp / "intent.json"
        if not intent_file.exists():
            return "waiting", "interactive: intent.json required"
        try:
            payload = json.loads(intent_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "waiting", "interactive: intent.json must contain valid JSON"
        valid, message = validate_intent_payload(payload)
        if not valid:
            return "waiting", f"interactive: {message}"
        return "done", str(intent_file)

    if phase == 2:
        ensure_dirs(video_id)
        url_file = temp / "url.txt"
        if not url_file.exists():
            url_file.write_text("https://www.youtube.com/watch?v=\n", encoding="utf-8")
            return "waiting", f"interactive: write youtube url to {url_file}"
        url = url_file.read_text(encoding="utf-8").strip()
        if not url or not is_valid_youtube_url(url):
            return "waiting", f"interactive: update {url_file} with a valid YouTube URL"
        return "done", f"setup done: temp={temp}, final={final}, url={url_file}"

    if phase == 3:
        url_file = temp / "url.txt"
        if not url_file.exists():
            return "failed", "url.txt not found"
        url = url_file.read_text(encoding="utf-8").strip()
        if not url:
            return "failed", "url.txt is empty"

        # Step 3a: metadata probe
        report_step(3, "metadata_probe", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_3_metadata_probe.py"), url, str(temp)],
            heartbeat_phase=3,
            heartbeat_name=PHASE_NAMES[3],
        )
        if exit_code != 0:
            report_step(3, "metadata_probe", "FAILED", output)
            return "failed", f"phase_3_metadata_probe failed: {output}"
        if not (temp / "metadata.json").exists():
            report_step(3, "metadata_probe", "FAILED", "metadata.json not produced")
            return "failed", "metadata.json not produced"
        report_step(3, "metadata_probe", "DONE", "output: temp/metadata.json")

        # Step 3b: caption discovery (reads metadata, writes caption_plan.json)
        subtitle_mode = (intent or {}).get("subtitle_mode", "auto")
        report_step(3, "caption_discovery", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_3_caption_discovery.py"), str(temp), subtitle_mode],
        )
        if exit_code != 0:
            report_step(3, "caption_discovery", "FAILED", output)
            return "failed", f"phase_3_caption_discovery failed: {output}"
        if not (temp / "caption_plan.json").exists():
            report_step(3, "caption_discovery", "FAILED", "caption_plan.json not produced")
            return "failed", "caption_plan.json not produced"
        report_step(3, "caption_discovery", "DONE", "output: temp/caption_plan.json")

        # Step 3c: video download
        report_step(3, "video_download", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_3_video_download.py"), url, str(temp)],
            heartbeat_phase=3,
            heartbeat_name=PHASE_NAMES[3],
        )
        if exit_code != 0:
            report_step(3, "video_download", "FAILED", output)
            return "failed", f"phase_3_video_download failed: {output}"
        raw_video = temp / "raw_video.mp4"
        if not raw_video.exists():
            report_step(3, "video_download", "FAILED", "raw_video.mp4 not produced")
            return "failed", "raw_video.mp4 not produced"
        report_step(3, "video_download", "DONE", "output: temp/raw_video.mp4")
        return "done", str(raw_video)

    if phase == 4:
        # Read caption_plan to determine path
        plan_file = temp / "caption_plan.json"
        if not plan_file.exists():
            return "failed", "caption_plan.json not found — run phase 3 first"
        try:
            caption_plan = json.loads(plan_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "failed", "caption_plan.json is invalid JSON"
        caption_source = caption_plan.get("source", "asr")

        # Step 4a: caption fetch (official) or ASR
        if caption_source == "official":
            # Official caption path
            url_file = temp / "url.txt"
            url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else ""
            if not url:
                return "failed", "url.txt not found for caption fetch"
            report_step(4, "caption_fetch", "RUNNING")
            exit_code, output = run_subprocess(
                [sys.executable, str(SKILL_ROOT / "scripts/phase_4_caption_fetch.py"), url, str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                report_step(4, "caption_fetch", "FAILED", output)
                return "failed", f"phase_4_caption_fetch failed: {output}"
            report_step(4, "caption_fetch", "DONE", "output: temp/source_segments.json")
        else:
            # ASR path: audio extract + ASR + normalize
            video_file = temp / "raw_video.mp4"
            if not video_file.exists():
                return "failed", "raw_video.mp4 not found — run phase 3 first"
            source_audio = temp / "source_audio.wav"
            if (SKILL_ROOT / "scripts/phase_4_audio_extract.py").exists():
                report_step(4, "audio_extract", "RUNNING")
                exit_code, output = run_subprocess(
                    [sys.executable, str(SKILL_ROOT / "scripts/phase_4_audio_extract.py"), str(video_file), str(temp)],
                    heartbeat_phase=4,
                    heartbeat_name=PHASE_NAMES[4],
                )
                if exit_code != 0:
                    report_step(4, "audio_extract", "FAILED", output)
                    return "failed", f"phase_4_audio_extract failed: {output}"
                report_step(4, "audio_extract", "DONE", "output: temp/source_audio.wav")

            report_step(4, "asr", "RUNNING")
            exit_code, output = run_subprocess(
                [sys.executable, str(SKILL_ROOT / "scripts/phase_4_asr.py"), str(source_audio if source_audio.exists() else video_file), str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                report_step(4, "asr", "FAILED", output)
                return "failed", f"phase_4_asr failed: {output}"
            report_step(4, "asr", "DONE", "output: temp/asr_segments.json")

            report_step(4, "asr_normalize", "RUNNING")
            exit_code, output = run_subprocess(
                [sys.executable, str(SKILL_ROOT / "scripts/phase_4_asr_normalize.py"), str(temp)],
            )
            if exit_code != 0:
                report_step(4, "asr_normalize", "FAILED", output)
                return "failed", f"phase_4_asr_normalize failed: {output}"
            report_step(4, "asr_normalize", "DONE", "output: temp/source_segments.json")

        # Step 4b: chunk build
        if not (temp / "chunks.json").exists():
            report_step(4, "chunk_build", "RUNNING")
            exit_code, output = run_subprocess(
                [sys.executable, str(SKILL_ROOT / "scripts/phase_4_chunk_build.py"), str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                report_step(4, "chunk_build", "FAILED", output)
                return "failed", f"phase_4_chunk_build failed: {output}"
            report_step(4, "chunk_build", "DONE", "output: temp/chunks.json")

        # Step 4c: translate scheduler (parallel chunk translation)
        vid = video_id
        if not vid:
            mfile = temp / "metadata.json"
            vid = json.loads(mfile.read_text()).get("video_id", "unknown") if mfile.exists() else "unknown"
        report_step(4, "translate_scheduler", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_4_translate_scheduler.py"),
             "--video-id", str(vid), "--temp-dir", str(temp)],
            heartbeat_phase=4,
            heartbeat_name=PHASE_NAMES[4],
        )
        if exit_code != 0:
            report_step(4, "translate_scheduler", "FAILED", output)
            return "failed", f"phase_4_translate_scheduler failed: {output}"
        report_step(4, "translate_scheduler", "DONE", "output: temp/chunks.json")

        # Step 4d: validate
        report_step(4, "validator", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_4_validator.py"), str(temp)],
        )
        if exit_code != 0:
            report_step(4, "validator", "FAILED", output)
            return "failed", f"phase_4_validator failed: {output}"
        report_step(4, "validator", "DONE")

        # Step 4e: align
        layout = (intent or {}).get("subtitle_layout", "bilingual")
        report_step(4, "align", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_4_align.py"), str(temp), layout],
        )
        if exit_code != 0:
            report_step(4, "align", "FAILED", output)
            return "failed", f"phase_4_align failed: {output}"
        report_step(4, "align", "DONE", "output: temp/subtitle_manifest.json")

        # Step 4f: export
        report_step(4, "export", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/phase_4_export.py"), str(temp), layout],
        )
        if exit_code != 0:
            report_step(4, "export", "FAILED", output)
            return "failed", f"phase_4_export failed: {output}"

        # Canonical output: subtitle_manifest.json + bilingual.ass / zh_only.ass
        layout_key = "bilingual" if layout == "bilingual" else "zh_only"
        canonical_ass = temp / f"{layout_key}.ass"
        if not canonical_ass.exists():
            report_step(4, "export", "FAILED", f"canonical subtitle {canonical_ass} not produced")
            return "failed", f"canonical subtitle {canonical_ass} not produced"
        # Also copy to subtitle_overlay.ass for Phase 7 compatibility
        overlay = temp / "subtitle_overlay.ass"
        overlay.write_bytes(canonical_ass.read_bytes())
        report_step(4, "export", "DONE", f"output: temp/{layout_key}.ass")
        return "done", str(canonical_ass)

    if phase == 5:
        if intent and intent.get("audio_mode") == "original":
            return "done", "skipped: original audio"

        # New architecture: TTS consumes subtitle_manifest.json
        manifest_file = temp / "subtitle_manifest.json"
        if not manifest_file.exists():
            return "failed", "subtitle_manifest.json not found — run phase 4 first"

        # Generate zh_translated.srt from manifest for voiceover_tts compatibility
        srt_file = temp / "zh_translated.srt"
        if not srt_file.exists():
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            lines = []
            for i, seg in enumerate(manifest_data.get("segments", []), start=1):
                start_ts = _seconds_to_srt(seg.get("start", 0))
                end_ts = _seconds_to_srt(seg.get("end", 0))
                text = seg.get("translated_text", "").replace("\n", "\\N")
                lines.append(f"{i}\n{start_ts} --> {end_ts}\n{text}")
            srt_file.write_text("\n\n".join(lines) + "\n", encoding="utf-8")

        output = temp / "zh_voiceover.mp3"
        if output.exists():
            return "done", str(output)

        exit_code, logs = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/voiceover_tts.py"), str(srt_file), str(output)],
            heartbeat_phase=5,
            heartbeat_name=PHASE_NAMES[5],
        )
        if exit_code == 0 and output.exists():
            return "done", str(output)
        return "failed", logs

    if phase == 6:
        cover = final / "cover_final.jpg"
        if cover.exists():
            return "done", str(cover)
        options_file = temp / "cover_options.json"
        if not options_file.exists():
            options = build_cover_options(video_id, temp, intent)
            options_file.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            try:
                options = json.loads(options_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                options = build_cover_options(video_id, temp, intent)
                options_file.write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")

        valid, selection, message = resolve_cover_selection(temp, options)
        if not valid:
            return "waiting", message

        background_image = selection["background_image"]
        if background_image:
            bg_path = Path(background_image)
        else:
            exit_code, bg_message = ensure_cover_background(temp)
            if exit_code != 0:
                return "failed", bg_message
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
            return "done", str(cover)
        return "failed", output or "cover generation failed"

    if phase == 7:
        video = temp / "raw_video.mp4"
        voiceover = temp / "zh_voiceover.mp3"
        final_video = final / "final_video.mp4"

        if not video.exists():
            return "failed", "raw_video.mp4 not found"
        exit_code, message = ensure_subtitle_overlay(temp, intent)
        if exit_code != 0:
            return "failed", message
        ass = Path(message)
        freshness_sources = [video, ass]
        if voiceover.exists():
            freshness_sources.append(voiceover)
        if final_video.exists() and target_is_fresh(final_video, freshness_sources):
            return "done", str(final_video)

        audio_arg = str(voiceover) if voiceover.exists() else ""
        cmd = [
            sys.executable, str(SKILL_ROOT / "scripts/video_muxer.py"),
            str(video), audio_arg, str(ass), str(final),
        ]
        if not voiceover.exists():
            cmd.append("--original-audio")

        exit_code, output = run_subprocess(
            cmd,
            heartbeat_phase=7,
            heartbeat_name=PHASE_NAMES[7],
        )
        if exit_code == 0 and final_video.exists():
            return "done", str(final_video)
        return "failed", output

    if phase == 8:
        video = final / "final_video.mp4"
        if not video.exists():
            return "failed", "final_video.mp4 not found"

        bin_id = video_id
        url = f"https://filebin.net/{bin_id}/final_video.mp4"
        exit_code, output = run_subprocess(
            [
                "curl", "-fsS", "-X", "PUT", "-H", "Content-Type: video/mp4",
                "--data-binary", f"@{video}", url,
            ],
            heartbeat_phase=8,
            heartbeat_name=PHASE_NAMES[8],
        )
        if exit_code != 0:
            return "failed", output or "file upload failed"

        preview_file = final / "preview.txt"
        if preview_file.exists() and target_is_fresh(preview_file, [video]):
            return "done", str(preview_file)

        preview_file.write_text(url, encoding="utf-8")
        return "done", str(preview_file)

    if phase == 9:
        if intent and not intent.get("publish"):
            return "done", "skipped: publishing not requested"

        final_video = final / "final_video.mp4"
        if not final_video.exists():
            return "failed", "final_video.mp4 not found — run phase 7 first"

        # Check publish mode via publish_result.json or prompt
        publish_result = final / "publish_result.json"
        publish_mode = "draft"  # default
        if publish_result.exists():
            try:
                pr_data = json.loads(publish_result.read_text(encoding="utf-8"))
                publish_mode = pr_data.get("mode", "draft")
            except (json.JSONDecodeError, OSError):
                pass

        if not publish_result.exists():
            return "waiting", f"interactive: choose publish mode (draft or formal), then write mode to final/publish_result.json"

        # draft path: upload to filebin only
        if publish_mode == "draft":
            preview_file = final / "preview.txt"
            if preview_file.exists() and target_is_fresh(preview_file, [final_video]):
                return "done", str(preview_file)
            return "done", "skipped: draft mode — preview already available"

        # formal path: full Bilibili publish via agent_browser
        return "waiting", "interactive: agent_browser_delegation_required"

    if phase == 10:
        cleanup_requested = bool(intent and intent.get("cleanup"))
        if not cleanup_requested:
            return "done", "skipped: cleanup not requested"
        if not temp.exists():
            return "done", "nothing to clean"

        exit_code, output = run_subprocess(
            [sys.executable, str(SKILL_ROOT / "scripts/cleaner.py"), str(temp)],
            heartbeat_phase=10,
            heartbeat_name=PHASE_NAMES[10],
        )
        return ("done", output) if exit_code == 0 else ("failed", output)

    return "failed", f"Unknown phase: {phase}"


def report_status(phase: int, status: str, msg: str = "", artifact: str = "") -> None:
    phase_name = PHASE_NAMES.get(phase, f"phase_{phase}")
    if status == "RUNNING":
        print(f"[Phase {phase}/10][RUNNING] {phase_name}")
    elif status == "DONE":
        out = f"[Phase {phase}/10][DONE] {phase_name}"
        if artifact:
            out += f" | output: {artifact}"
        print(out)
    elif status == "WAIT":
        reason = msg or "waiting for input"
        print(f"[Phase {phase}/10][WAIT] {phase_name} | reason: {reason}")
    elif status == "SKIP":
        reason = msg or "already completed"
        print(f"[Phase {phase}/10][SKIP] {phase_name} | reason: {reason}")
    elif status == "FAILED":
        print(f"[Phase {phase}/10][FAILED] {phase_name} | error: {msg}")


def run_single_phase(video_id: str, phase: int, intent: dict | None = None) -> str:
    next_pending = get_next_pending_phase(video_id)
    stale = phase_needs_refresh(video_id, phase, intent)

    if is_phase_completed(video_id, phase) and not stale:
        report_status(phase, "SKIP", "already completed")
        return "done"

    if phase < next_pending and not stale:
        report_status(phase, "SKIP", f"phase {phase} already completed")
        return "done"

    if phase > next_pending:
        msg = f"phase {next_pending} must complete before running phase {phase}"
        report_status(phase, "FAILED", msg=msg)
        return "failed"

    report_status(phase, "RUNNING")
    update_phase(video_id, phase, "running")

    outcome, msg = run_phase_command(phase, video_id, intent)
    artifact = msg.split("\n")[-1] if msg else ""

    if outcome == "done":
        update_phase(video_id, phase, "done", artifact=artifact)
        report_status(phase, "DONE", artifact=artifact)
        return "done"

    if outcome == "waiting":
        update_phase(video_id, phase, "waiting", artifact=artifact)
        report_status(phase, "WAIT", msg=artifact)
        return "waiting"

    update_phase(video_id, phase, "failed", error=msg)
    report_status(phase, "FAILED", msg=msg)
    return "failed"


def phase_needs_refresh(video_id: str, phase: int, intent: dict | None = None) -> bool:
    temp = get_temp_dir(video_id)
    final = get_final_dir(video_id)

    if phase == 7:
        final_video = final / "final_video.mp4"
        ass = temp / "subtitle_overlay.ass"
        video = temp / "raw_video.mp4"
        voiceover = temp / "zh_voiceover.mp3"
        style_config = get_subtitle_style_path(temp)
        layout = (intent or {}).get("subtitle_layout", "bilingual")
        subtitle_sources = [temp / "zh_translated.srt", style_config]
        if layout == "bilingual":
            subtitle_sources.append(temp / "en_audited.srt")
        if not ass.exists() or not target_is_fresh(ass, subtitle_sources):
            return True
        if not final_video.exists():
            return True
        sources = [video, ass]
        if voiceover.exists():
            sources.append(voiceover)
        return not target_is_fresh(final_video, sources)

    if phase == 8:
        final_video = final / "final_video.mp4"
        preview_file = final / "preview.txt"
        if not final_video.exists() or not preview_file.exists():
            return True
        return not target_is_fresh(preview_file, [final_video])

    return False


def run_from_state(video_id: str, intent: dict | None = None) -> str:
    while True:
        next_phase = get_next_pending_phase(video_id)
        if next_phase > 10:
            return "done"

        outcome = run_single_phase(video_id, next_phase, intent)
        if outcome != "done":
            return outcome


def load_intent(video_id: str) -> dict:
    intent_file = get_temp_dir(video_id) / "intent.json"
    if not intent_file.exists():
        return {}
    try:
        intent = json.loads(intent_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    valid, _ = validate_intent_payload(intent)
    return intent if valid else {}


def main():
    ensure_mise_environment()
    if len(sys.argv) < 3:
        print("Usage:")
        print("  phase_runner.py run --video-id [ID]           # Run all pending phases")
        print("  phase_runner.py run --video-id [ID] --phase N # Run specific phase")
        print("  phase_runner.py status --video-id [ID]        # Show current state")
        print("  phase_runner.py reset --video-id [ID]         # Reset state")
        sys.exit(1)

    command = sys.argv[1]

    if command == "run":
        video_id = None
        specific_phase = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--video-id" and i + 1 < len(args):
                video_id = args[i + 1]
                i += 2
            elif args[i] == "--phase" and i + 1 < len(args):
                specific_phase = int(args[i + 1])
                i += 2
            else:
                i += 1

        if not video_id:
            print("Error: --video-id required")
            sys.exit(1)

        # 确保状态文件在任务开始时就存在
        load_state(video_id)
        # 如果是初次运行，save_state 会由 load_state 间接触发（如果逻辑需要），
        # 但显式保存一次初始状态更稳妥。
        from state_manager import save_state
        initial_state = load_state(video_id)
        save_state(video_id, initial_state)

        intent = load_intent(video_id)
        outcome = run_single_phase(video_id, specific_phase, intent) if specific_phase is not None else run_from_state(video_id, intent)
        sys.exit(0 if outcome in {"done", "waiting"} else 1)

    if command == "status":
        if len(sys.argv) < 4 or sys.argv[2] != "--video-id":
            print("Error: --video-id required")
            sys.exit(1)
        video_id = sys.argv[3]
        state = load_state(video_id)
        print(json.dumps(state, indent=2, ensure_ascii=False))
        sys.exit(0)

    if command == "reset":
        if len(sys.argv) < 4 or sys.argv[2] != "--video-id":
            print("Error: --video-id required")
            sys.exit(1)
        video_id = sys.argv[3]
        state_path = get_state_path(video_id)
        if state_path.exists():
            state_path.unlink()
        print(f"Reset state for {video_id}")
        sys.exit(0)

    print(f"Unknown command: {command}")
    sys.exit(1)


if __name__ == "__main__":
    main()
