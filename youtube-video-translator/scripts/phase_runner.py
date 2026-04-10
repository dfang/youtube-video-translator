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


def get_subtitle_style_path(temp_dir: Path) -> Path:
    return temp_dir / STYLE_CONFIG_FILENAME


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
        layout = (intent or {}).get("subtitle_layout", "bilingual")
        
        exit_code, output = run_subprocess(
            [
                sys.executable, str(SKILL_ROOT / "scripts/phase_4_pipeline.py"),
                "--video-id", video_id,
                "--temp-dir", str(temp),
                "--layout", layout
            ],
            heartbeat_phase=4,
            heartbeat_name=PHASE_NAMES[4]
        )
        if exit_code == 0:
            layout_key = "bilingual" if layout == "bilingual" else "zh_only"
            canonical_ass = temp / f"{layout_key}.ass"
            return "done", str(canonical_ass)
        return "failed", output

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
        layout = (intent or {}).get("subtitle_layout", "bilingual")
        original_audio = (intent or {}).get("audio_mode") == "original"
        
        cmd = [
            sys.executable, str(SKILL_ROOT / "scripts/phase_6_video_muxer.py"),
            "--video-id", video_id,
            "--temp-dir", str(temp),
            "--final-dir", str(final),
            "--layout", layout
        ]
        if original_audio:
            cmd.append("--original-audio")

        exit_code, output = run_subprocess(
            cmd,
            heartbeat_phase=6,
            heartbeat_name=PHASE_NAMES[6],
        )
        if exit_code == 0:
            final_video = final / "final_video.mp4"
            return "done", str(final_video)
        return "failed", output

    if phase == 7:
        layout = (intent or {}).get("subtitle_layout", "bilingual")
        exit_code, output = run_subprocess(
            [
                sys.executable, str(SKILL_ROOT / "scripts/phase_7_cover.py"),
                "--video-id", video_id,
                "--temp-dir", str(temp),
                "--final-dir", str(final),
                "--layout", layout
            ],
            heartbeat_phase=7,
            heartbeat_name=PHASE_NAMES[7]
        )
        if exit_code == 0:
            if output.startswith("WAIT:"):
                return "waiting", output
            if output.startswith("interactive:"):
                return "waiting", output
            cover = final / "cover_final.jpg"
            if cover.exists():
                return "done", str(cover)
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

    if phase == 6:
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
