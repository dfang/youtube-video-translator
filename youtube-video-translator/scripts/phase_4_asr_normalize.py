#!/usr/bin/env python3
"""
Phase 4, Step 3: ASR Normalize

Reads temp/asr_segments.json, normalizes the content,
and writes to temp/source_segments.json (the unified segment contract).

This is only run for the ASR path. The output must have the same
schema as the official caption path so both can feed the same chunks.json.

Idempotent: skips if source_segments.json already exists for ASR path.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def is_source_segments_fresh_asr(temp_dir: Path) -> bool:
    f = temp_dir / "source_segments.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("source") == "asr"
    except (json.JSONDecodeError, OSError):
        return False


def normalize_asr(temp_dir: Path) -> tuple[int, str]:
    temp_dir = Path(temp_dir)
    asr_file = temp_dir / "asr_segments.json"

    if not asr_file.exists():
        return 1, f"asr_segments.json not found at {asr_file}"

    if is_source_segments_fresh_asr(temp_dir):
        print("[phase_4_asr_normalize] source_segments.json (asr) already fresh, skipping.")
        return 0, str(temp_dir / "source_segments.json")

    asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
    asr_segments = asr_data.get("segments", [])

    if not asr_segments:
        return 1, "asr_segments.json contains no segments"

    # Convert asr_segments format to source_segments format
    # Both must have: start, end, text (index is optional but useful for debugging)
    source_segments = []
    for i, seg in enumerate(asr_segments, start=1):
        item = {
            "index": i,
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": seg.get("text", ""),
        }
        words = seg.get("words")
        if isinstance(words, list) and words:
            item["words"] = words
        speaker = seg.get("speaker")
        if speaker:
            item["speaker"] = speaker
        source_segments.append(item)

    source_data = {
        "video_id": asr_data.get("video_id", ""),
        "source": "asr",
        "language": "en",
        "segments": source_segments,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        # Preserve ASR metadata
        "asr_model": asr_data.get("model"),
    }

    out_file = temp_dir / "source_segments.json"
    out_file.write_text(json.dumps(source_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_4_asr_normalize] source_segments.json written: {len(source_segments)} segments (from asr)")
    return 0, str(out_file)


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_asr_normalize.py [TempDir]")
        sys.exit(1)
    temp_dir = Path(sys.argv[1])
    exit_code, msg = normalize_asr(temp_dir)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
