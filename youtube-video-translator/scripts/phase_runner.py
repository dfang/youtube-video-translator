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


def get_video_dir(video_id: str) -> Path:
    return Path(f"./translations/{video_id}")


def get_temp_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "temp"


def get_final_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "final"


def ensure_dirs(video_id: str) -> None:
    get_temp_dir(video_id).mkdir(parents=True, exist_ok=True)
    get_final_dir(video_id).mkdir(parents=True, exist_ok=True)


def run_subprocess(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


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


def ensure_source_subtitles(temp_dir: Path) -> tuple[int, str]:
    en_original = temp_dir / "en_original.srt"
    if en_original.exists():
        return 0, str(en_original)

    official = find_existing_official_srt(temp_dir)
    if official:
        en_original.write_text(official.read_text(encoding="utf-8"), encoding="utf-8")
        return 0, str(en_original)

    raw_video = temp_dir / "raw_video.mp4"
    if not raw_video.exists():
        return 1, "raw_video.mp4 not found"

    exit_code, output = run_subprocess(
        ["python3", str(SKILL_ROOT / "scripts/whisperx_transcriber.py"), str(raw_video), str(temp_dir)]
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


def run_phase_command(phase: int, video_id: str, intent: dict | None = None) -> tuple[str, str]:
    temp = get_temp_dir(video_id)
    final = get_final_dir(video_id)

    if phase == 0:
        exit_code, output = run_subprocess(["python3", str(SKILL_ROOT / "scripts/env_check.py")])
        return ("done", output) if exit_code == 0 else ("failed", output)

    if phase == 1:
        intent_file = temp / "intent.json"
        if intent_file.exists():
            return "done", str(intent_file)
        return "waiting", "interactive: intent.json required"

    if phase == 2:
        ensure_dirs(video_id)
        url_file = temp / "url.txt"
        if not url_file.exists():
            return "failed", "url.txt not found in temp/"
        return "done", f"setup done: temp={temp}, final={final}"

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
            ["python3", str(SKILL_ROOT / "scripts/downloader.py"), url, str(temp)]
        )
        if exit_code == 0 and raw_video.exists():
            return "done", str(raw_video)
        return "failed", output

    if phase == 4:
        if not (temp / "en_audited.srt").exists():
            exit_code, message = ensure_source_subtitles(temp)
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
                ["python3", str(SKILL_ROOT / "scripts/phase4_runner.py"), "start", str(srt), str(temp)]
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
                ["python3", str(SKILL_ROOT / "scripts/phase4_runner.py"), "finalize", str(temp)]
            )
            if exit_code != 0:
                return "failed", output

        exit_code, message = ensure_bilingual_ass(temp)
        if exit_code != 0:
            return "failed", message
        return "done", str(zh_translated)

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
            ["python3", str(SKILL_ROOT / "scripts/voiceover_tts.py"), str(srt), str(output)]
        )
        if exit_code == 0 and output.exists():
            return "done", str(output)
        return "failed", logs

    if phase == 6:
        cover = final / "cover_final.jpg"
        if cover.exists():
            return "done", str(cover)
        return "waiting", "interactive: user_title_selection_required"

    if phase == 7:
        video = temp / "raw_video.mp4"
        ass = temp / "bilingual.ass"
        voiceover = temp / "zh_voiceover.mp3"
        final_video = final / "final_video.mp4"

        if not video.exists():
            return "failed", "raw_video.mp4 not found"
        if not ass.exists():
            return "failed", "bilingual.ass not found"
        if final_video.exists():
            return "done", str(final_video)

        audio_arg = str(voiceover) if voiceover.exists() else ""
        cmd = [
            "python3", str(SKILL_ROOT / "scripts/video_muxer.py"),
            str(video), audio_arg, str(ass), str(final),
        ]
        if not voiceover.exists():
            cmd.append("--original-audio")

        exit_code, output = run_subprocess(cmd)
        if exit_code == 0 and final_video.exists():
            return "done", str(final_video)
        return "failed", output

    if phase == 8:
        video = final / "final_video.mp4"
        if not video.exists():
            return "failed", "final_video.mp4 not found"

        bin_id = video_id
        url = f"https://filebin.net/{bin_id}/final_video.mp4"
        result = subprocess.run(
            [
                "curl", "-fsS", "-X", "PUT", "-H", "Content-Type: video/mp4",
                "--data-binary", f"@{video}", url,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output = ((result.stdout or "") + (result.stderr or "")).strip()
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

        exit_code, output = run_subprocess(["python3", str(SKILL_ROOT / "scripts/cleaner.py"), str(temp)])
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
        return json.loads(intent_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


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
