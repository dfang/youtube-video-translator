#!/usr/bin/env python3
"""
Phase 4: Subtitle Pipeline.
Orchestrates caption fetch/ASR, chunking, translation, validation, and export.
"""

import sys
import json
import argparse
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

from utils import run_subprocess
from state_manager import PHASE_NAMES

def report_step(step: str, status: str, msg: str = "") -> None:
    if status == "RUNNING":
        print(f"[Phase 4/11][STEP][RUNNING] {step}")
    elif status == "DONE":
        line = f"[Phase 4/11][STEP][DONE] {step}"
        if msg:
            line += f" | {msg}"
        print(line)
    elif status == "FAILED":
        line = f"[Phase 4/11][STEP][FAILED] {step}"
        if msg:
            line += f" | error: {msg}"
        print(line)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--layout", default="bilingual")
    args = parser.parse_args()

    temp = Path(args.temp_dir)
    video_id = args.video_id
    layout = args.layout

    # Read caption_plan to determine path
    plan_file = temp / "caption_plan.json"
    if not plan_file.exists():
        print("Error: caption_plan.json not found — run phase 3 first")
        sys.exit(1)
    
    try:
        caption_plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("Error: caption_plan.json is invalid JSON")
        sys.exit(1)
    
    caption_source = caption_plan.get("source", "asr")

    # Step 4a: caption fetch (official) or ASR
    if caption_source == "official":
        url_file = temp / "url.txt"
        url = url_file.read_text(encoding="utf-8").strip() if url_file.exists() else ""
        if not url:
            print("Error: url.txt not found for caption fetch")
            sys.exit(1)
        
        report_step("caption_fetch", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(Path(__file__).parent / "caption_fetch.py"), url, str(temp)],
            heartbeat_phase=4,
            heartbeat_name=PHASE_NAMES[4],
        )
        if exit_code != 0:
            report_step("caption_fetch", "FAILED", output)
            sys.exit(exit_code)
        report_step("caption_fetch", "DONE", "output: temp/source_segments.json")
    else:
        # ASR path: audio extract + ASR + normalize
        video_file = temp / "raw_video.mp4"
        if not video_file.exists():
            print("Error: raw_video.mp4 not found — run phase 3 first")
            sys.exit(1)
        
        source_audio = temp / "source_audio.wav"
        if (Path(__file__).parent / "audio_extract.py").exists():
            report_step("audio_extract", "RUNNING")
            exit_code, output = run_subprocess(
                [sys.executable, str(Path(__file__).parent / "audio_extract.py"), str(video_file), str(temp)],
                heartbeat_phase=4,
                heartbeat_name=PHASE_NAMES[4],
            )
            if exit_code != 0:
                report_step("audio_extract", "FAILED", output)
                sys.exit(exit_code)
            report_step("audio_extract", "DONE", "output: temp/source_audio.wav")

        report_step("asr", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(Path(__file__).parent / "asr.py"), str(source_audio if source_audio.exists() else video_file), str(temp)],
            heartbeat_phase=4,
            heartbeat_name=PHASE_NAMES[4],
        )
        if exit_code != 0:
            report_step("asr", "FAILED", output)
            sys.exit(exit_code)
        report_step("asr", "DONE", "output: temp/asr_segments.json")

        report_step("asr_normalize", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(Path(__file__).parent / "asr_normalize.py"), str(temp)],
        )
        if exit_code != 0:
            report_step("asr_normalize", "FAILED", output)
            sys.exit(exit_code)
        report_step("asr_normalize", "DONE", "output: temp/source_segments.json")

    # Step 4b: chunk build
    if not (temp / "chunks.json").exists():
        report_step("chunk_build", "RUNNING")
        exit_code, output = run_subprocess(
            [sys.executable, str(Path(__file__).parent / "chunk_build.py"), str(temp)],
            heartbeat_phase=4,
            heartbeat_name=PHASE_NAMES[4],
        )
        if exit_code != 0:
            report_step("chunk_build", "FAILED", output)
            sys.exit(exit_code)
        report_step("chunk_build", "DONE", "output: temp/chunks.json")

    # Step 4c: translate scheduler
    report_step("translate_scheduler", "RUNNING")
    exit_code, output = run_subprocess(
        [sys.executable, str(Path(__file__).parent / "translate_scheduler.py"),
            "--video-id", video_id, "--temp-dir", str(temp)],
        heartbeat_phase=4,
        heartbeat_name=PHASE_NAMES[4],
    )
    if exit_code != 0:
        report_step("translate_scheduler", "FAILED", output)
        sys.exit(exit_code)
    report_step("translate_scheduler", "DONE", "output: temp/chunks.json")

    # Step 4d: validate
    report_step("validator", "RUNNING")
    exit_code, output = run_subprocess(
        [sys.executable, str(Path(__file__).parent / "validator.py"), str(temp)],
    )
    if exit_code != 0:
        report_step("validator", "FAILED", output)
        sys.exit(exit_code)
    report_step("validator", "DONE")

    # Step 4e: align
    report_step("align", "RUNNING")
    exit_code, output = run_subprocess(
        [sys.executable, str(Path(__file__).parent / "align.py"), str(temp), layout],
    )
    if exit_code != 0:
        report_step("align", "FAILED", output)
        sys.exit(exit_code)
    report_step("align", "DONE", "output: temp/subtitle_manifest.json")

    # Step 4f: export
    report_step("export", "RUNNING")
    exit_code, output = run_subprocess(
        [sys.executable, str(Path(__file__).parent / "export.py"), str(temp), layout],
    )
    if exit_code != 0:
        report_step("export", "FAILED", output)
        sys.exit(exit_code)

    # Canonical output
    layout_key = "bilingual" if layout == "bilingual" else "zh_only"
    canonical_ass = temp / f"{layout_key}.ass"
    if not canonical_ass.exists():
        print(f"Error: canonical subtitle {canonical_ass} not produced")
        sys.exit(1)
    
    # Copy to subtitle_overlay.ass for Phase 7 compatibility
    overlay = temp / "subtitle_overlay.ass"
    overlay.write_bytes(canonical_ass.read_bytes())
    report_step("export", "DONE", f"output: {canonical_ass}")
    
    print(str(canonical_ass))
    sys.exit(0)

if __name__ == "__main__":
    main()
