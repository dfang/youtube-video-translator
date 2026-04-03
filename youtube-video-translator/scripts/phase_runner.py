#!/usr/bin/env python3
"""
Unified phase runner for youtube-video-translator.
Handles phase ordering, checkpointing, and resumable execution.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent
_installed_root = Path(os.environ.get("HOME")) / ".openclaw/skills/youtube-video-translator"

# Prefer installed path if it has agents/ (production), otherwise use dev checkout
if _installed_root.exists() and (_installed_root / "agents").exists():
    SKILL_ROOT = _installed_root
else:
    SKILL_ROOT = _dev_root

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from state_manager import get_state_path, load_state, update_phase, is_phase_completed, get_next_pending_phase, PHASE_NAMES
from utils import get_ffmpeg_path


INTENT_ENUMS = {
    "audio_mode": {"original", "voiceover"},
    "subtitle_mode": {"auto", "official_only", "transcribe"},
    "subtitle_layout": {"bilingual", "chinese_only"},
}


def get_video_dir(video_id: str) -> Path:
    return Path(f"./translations/{video_id}")


def get_temp_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "temp"


def get_final_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "final"


def ensure_dirs(video_id: str) -> None:
    get_temp_dir(video_id).mkdir(parents=True, exist_ok=True)
    get_final_dir(video_id).mkdir(parents=True, exist_ok=True)


def run_subprocess(
    cmd: list[str],
    heartbeat_phase: int | None = None,
    heartbeat_name: str | None = None,
    heartbeat_interval: int = 60,
) -> tuple[int, str]:
    if heartbeat_phase is None or heartbeat_name is None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stream:
        process = subprocess.Popen(cmd, stdout=stream, stderr=stream, text=True)
        started_at = time.monotonic()
        last_heartbeat = started_at

        while True:
            try:
                returncode = process.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_interval:
                    elapsed = int(now - started_at)
                    print(f"[Phase {heartbeat_phase}/10][HEARTBEAT] {heartbeat_name} | elapsed: {elapsed}s")
                    last_heartbeat = now

        stream.seek(0)
        output = stream.read().strip()
        return returncode, output


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def parse_srt_blocks(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    blocks = re.split(r"\n\s*\n", content)
    parsed = []
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines()]
        if len(lines) < 3:
            continue
        parsed.append(
            {
                "index": lines[0].strip(),
                "timecode": lines[1].strip(),
                "text": "\n".join(lines[2:]).strip(),
            }
        )
    return parsed


def write_srt_blocks(path: Path, blocks: list[dict]) -> None:
    rendered = []
    for block in blocks:
        rendered.append(f"{block['index']}\n{block['timecode']}\n{block['text']}")
    path.write_text("\n\n".join(rendered) + ("\n" if rendered else ""), encoding="utf-8")


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
        ["python3", str(SKILL_ROOT / "scripts/whisperx_transcriber.py"), str(raw_video), str(temp_dir)],
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
        ["python3", str(SKILL_ROOT / "scripts/subtitle_splitter.py"), str(en_original), str(en_audited)]
    )
    if exit_code != 0:
        return exit_code, output
    compat_audited.write_text(en_audited.read_text(encoding="utf-8"), encoding="utf-8")
    return 0, str(en_audited)


def ensure_chinese_ass(temp_dir: Path) -> tuple[int, str]:
    zh_translated = temp_dir / "zh_translated.srt"
    zh_only_ass = temp_dir / "zh_only.ass"

    if zh_only_ass.exists():
        return 0, str(zh_only_ass)
    if not zh_translated.exists():
        return 1, "zh_translated.srt not found"

    exit_code, output = run_subprocess(
        ["python3", str(SKILL_ROOT / "scripts/srt_to_ass.py"), str(zh_translated), str(zh_only_ass)]
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

    if bilingual_ass.exists():
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
        ["python3", str(SKILL_ROOT / "scripts/srt_to_ass.py"), str(bilingual_srt), str(bilingual_ass)]
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


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        normalized = " ".join(item.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def shorten_text(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


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
            ["python3", str(SKILL_ROOT / "scripts/env_check.py")],
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

        raw_video = temp / "raw_video.mp4"
        if raw_video.exists():
            return "done", str(raw_video)

        exit_code, output = run_subprocess(
            ["python3", str(SKILL_ROOT / "scripts/downloader.py"), url, str(temp)],
            heartbeat_phase=3,
            heartbeat_name=PHASE_NAMES[3],
        )
        if exit_code == 0 and raw_video.exists():
            return "done", str(raw_video)
        return "failed", output

    if phase == 4:
        if not (temp / "en_audited.srt").exists():
            exit_code, message = ensure_source_subtitles(temp, intent)
            if exit_code != 0:
                return "failed", message

            exit_code, message = ensure_audited_subtitles(temp)
            if exit_code != 0:
                return "failed", message
        else:
            exit_code, message = ensure_audited_subtitles(temp)
            if exit_code != 0:
                return "failed", message

        srt = temp / "en_audited.srt"
        p4_state = temp / "phase4_state.json"
        zh_translated = temp / "zh_translated.srt"

        if not p4_state.exists():
            exit_code, output = run_subprocess(
                ["python3", str(SKILL_ROOT / "scripts/phase4_runner.py"), "start", str(srt), str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                return "failed", output

        exit_code, output = run_subprocess(
            ["python3", str(SKILL_ROOT / "scripts/phase4_runner.py"), "status", str(temp), "--json"]
        )
        if exit_code != 0:
            return "failed", output

        try:
            status_data = json.loads(output)
        except json.JSONDecodeError:
            return "failed", f"phase4 status returned invalid JSON: {output}"

        verified = status_data.get("counts", {}).get("verified", 0)
        total = status_data.get("total_batches", 0)
        if verified != total or total == 0:
            return "waiting", "interactive: phase4_batch_translation_required"

        if not zh_translated.exists():
            exit_code, output = run_subprocess(
                ["python3", str(SKILL_ROOT / "scripts/phase4_runner.py"), "finalize", str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                return "failed", output

        exit_code, message = ensure_subtitle_overlay(temp, intent)
        if exit_code != 0:
            return "failed", message
        return "done", message

    if phase == 5:
        if intent and intent.get("audio_mode") == "original":
            return "done", "skipped: original audio"

        srt = temp / "zh_translated.srt"
        output = temp / "zh_voiceover.mp3"
        if not srt.exists():
            return "failed", "zh_translated.srt not found"
        if output.exists():
            return "done", str(output)

        exit_code, logs = run_subprocess(
            ["python3", str(SKILL_ROOT / "scripts/voiceover_tts.py"), str(srt), str(output)],
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
                "python3",
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
        ass = temp / "subtitle_overlay.ass"
        voiceover = temp / "zh_voiceover.mp3"
        final_video = final / "final_video.mp4"

        if not video.exists():
            return "failed", "raw_video.mp4 not found"
        if not ass.exists():
            exit_code, message = ensure_subtitle_overlay(temp, intent)
            if exit_code != 0:
                return "failed", message
            ass = Path(message)
        if final_video.exists():
            return "done", str(final_video)

        audio_arg = str(voiceover) if voiceover.exists() else ""
        cmd = [
            "python3", str(SKILL_ROOT / "scripts/video_muxer.py"),
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
        preview_file.write_text(url, encoding="utf-8")
        return "done", str(preview_file)

    if phase == 9:
        if intent and not intent.get("publish"):
            return "done", "skipped: publishing not requested"
        if final.joinpath("publish_result.json").exists():
            return "done", str(final / "publish_result.json")
        return "waiting", "interactive: agent_browser_delegation_required"

    if phase == 10:
        cleanup_requested = bool(intent and intent.get("cleanup"))
        if not cleanup_requested:
            return "done", "skipped: cleanup not requested"
        if not temp.exists():
            return "done", "nothing to clean"

        exit_code, output = run_subprocess(
            ["python3", str(SKILL_ROOT / "scripts/cleaner.py"), str(temp)],
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

    if is_phase_completed(video_id, phase):
        report_status(phase, "SKIP", "already completed")
        return "done"

    if phase < next_pending:
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
