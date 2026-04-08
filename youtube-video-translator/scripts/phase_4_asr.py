#!/usr/bin/env python3
"""
Phase 4, Step 2: ASR Transcription (WhisperX)

ASR path: extracts audio via ffmpeg, runs WhisperX.
Outputs temp/asr_segments.json (intermediate, not consumed directly by chunking).

Idempotent: skips if asr_segments.json already exists.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SYS_PATH = str(SKILL_ROOT / "scripts")
sys.path.insert(0, SYS_PATH)

try:
    from utils import get_ffmpeg_path
except ImportError:
    get_ffmpeg_path = lambda: "ffmpeg"  # fallback


def normalize_timestamp(ts: str) -> float:
    """Convert SRT-style timestamp to float seconds."""
    ts = ts.replace(",", ".").strip()
    h, m, rest = ts.split(":")
    sec, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def compact_words(words: list[dict] | None) -> list[dict]:
    compacted = []
    for word in words or []:
        token = (word.get("word") or word.get("text") or "").strip()
        start = _safe_float(word.get("start"))
        end = _safe_float(word.get("end"))
        if not token:
            continue
        compacted.append({
            "text": token,
            "start": start,
            "end": end,
            "score": _safe_float(word.get("score")),
        })
    return compacted


def parse_whisperx_json(json_text: str) -> tuple[list[dict], str | None]:
    payload = json.loads(json_text)
    raw_segments = payload.get("segments", [])
    segments = []
    for seg in raw_segments:
        start = _safe_float(seg.get("start"))
        end = _safe_float(seg.get("end"))
        text = (seg.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        item = {
            "start": start,
            "end": end,
            "text": text,
        }
        words = compact_words(seg.get("words"))
        if words:
            item["words"] = words
        speaker = seg.get("speaker")
        if speaker:
            item["speaker"] = speaker
        segments.append(item)
    return segments, payload.get("language")


def parse_srt_segments(srt_text: str) -> list[dict]:
    import re
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    segments = []
    time_re = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")

    for block in blocks:
        lines = [l.rstrip("\r") for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        tm = time_re.search(lines[1])
        if not tm:
            continue
        segments.append({
            "start": normalize_timestamp(tm.group(1)),
            "end": normalize_timestamp(tm.group(2)),
            "text": "\n".join(lines[2:]).strip(),
        })
    return segments


def is_asr_fresh(temp_dir: Path) -> bool:
    f = temp_dir / "asr_segments.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return len(data.get("segments", [])) > 0 and bool(data.get("model"))
    except (json.JSONDecodeError, OSError):
        return False


def get_video_id(temp_dir: Path) -> str:
    metadata_file = temp_dir / "metadata.json"
    if metadata_file.exists():
        try:
            return json.loads(metadata_file.read_text(encoding="utf-8")).get("video_id", "")
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def run_asr(video_path: str, temp_dir: Path, model: str = "medium") -> tuple[int, str]:
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    if is_asr_fresh(temp_dir):
        print("[phase_4_asr] asr_segments.json already fresh, skipping.")
        return 0, str(temp_dir / "asr_segments.json")

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return 1, "FFmpeg not found. Cannot extract audio for ASR."

    audio_path = temp_dir / "original_audio.wav"

    # Step 1: extract audio (16kHz mono PCM — required by WhisperX)
    print(f"[phase_4_asr] Extracting audio to {audio_path}...")
    result = subprocess.run(
        [ffmpeg, "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio_path), "-y"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.returncode, f"ffmpeg audio extraction failed: {result.stderr[:300]}"

    # Step 2: run WhisperX
    print(f"[phase_4_asr] Running WhisperX ({model})...")
    whisperx_cmd = [
        "whisperx", str(audio_path),
        "--model", model,
        "--language", "en",
        "--output_dir", str(temp_dir),
        "--output_format", "all",
        "--compute_type", "int8",
    ]
    result = subprocess.run(whisperx_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return result.returncode, f"WhisperX failed: {result.stderr[:300]}"

    # WhisperX outputs original_audio.srt and original_audio.json when available.
    generated_srt = temp_dir / "original_audio.srt"
    generated_json = temp_dir / "original_audio.json"
    if not generated_srt.exists():
        return 1, f"WhisperX exited 0 but did not produce {generated_srt}"

    detected_language = "en"
    if generated_json.exists():
        try:
            segments, detected_language = parse_whisperx_json(generated_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[phase_4_asr] Warning: failed to parse WhisperX JSON, falling back to SRT: {exc}")
            segments = []
    else:
        segments = []

    if not segments:
        segments = parse_srt_segments(generated_srt.read_text(encoding="utf-8"))

    video_id = get_video_id(temp_dir)
    asr_data = {
        "video_id": video_id,
        "source": "asr",
        "model": model,
        "language": detected_language or "en",
        "segments": segments,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    out_file = temp_dir / "asr_segments.json"
    out_file.write_text(json.dumps(asr_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_4_asr] asr_segments.json written: {len(segments)} segments")
    return 0, str(out_file)


def main():
    if len(sys.argv) < 3:
        print("Usage: phase_4_asr.py [VideoPath] [TempDir] [Model可选]")
        sys.exit(1)
    video_path = sys.argv[1]
    temp_dir = Path(sys.argv[2])
    model = sys.argv[3] if len(sys.argv) > 3 else "medium"

    exit_code, msg = run_asr(video_path, temp_dir, model)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
