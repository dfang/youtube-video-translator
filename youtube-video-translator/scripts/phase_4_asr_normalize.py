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

# Sentence-splitting config
MAX_SEGMENT_DURATION = 8.0  # seconds — split if segment exceeds this
PAUSE_THRESHOLD = 0.8       # seconds — split on gap larger than this between words
SENTENCE_END_CHARS = frozenset(".!?")


def split_segment_by_words(seg: dict) -> list[dict]:
    """Split a single ASR segment into shorter sub-segments using word-level timestamps.

    Splits are triggered by:
      1. Sentence-ending punctuation (., ?, !) followed by whitespace or end of text
      2. A pause between words longer than PAUSE_THRESHOLD seconds
      3. The accumulated duration exceeding MAX_SEGMENT_DURATION seconds

    Returns a list of sub-segment dicts with start, end, text fields.
    """
    words = seg.get("words")
    if not isinstance(words, list) or len(words) == 0:
        return [{"start": seg["start"], "end": seg["end"], "text": seg.get("text", "")}]

    sub_segments = []
    sub_start = words[0]["start"]
    sub_end = sub_start
    sub_text_parts = []
    sentence_buffer = ""

    for i, word in enumerate(words):
        w_start = word.get("start", 0)
        w_end = word.get("end", w_start)
        w_text = word.get("text", "")
        w_punct = word.get("punct", "")

        text_to_append = w_text
        if w_punct:
            text_to_append = w_text + w_punct

        # Determine if we should break before this word
        should_break = False

        # Break on sentence-ending punctuation
        if sentence_buffer and sentence_buffer[-1] in SENTENCE_END_CHARS:
            should_break = True

        # Break on long pause from previous word
        if sub_text_parts and i > 0:
            prev_word = words[i - 1]
            prev_end = prev_word.get("end", 0)
            pause = w_start - prev_end
            if pause > PAUSE_THRESHOLD:
                should_break = True

        # Break if accumulated duration would exceed max
        seg_duration = w_end - sub_start
        if seg_duration > MAX_SEGMENT_DURATION and len(sub_text_parts) >= 2:
            should_break = True

        if should_break:
            # Finalize current sub-segment
            sub_text = "".join(sub_text_parts).strip()
            if sub_text:
                sub_segments.append({
                    "start": sub_start,
                    "end": sub_end,
                    "text": sub_text,
                })
            # Start new sub-segment
            sub_start = w_start
            sub_text_parts = []
            sentence_buffer = ""

        sub_text_parts.append(text_to_append)
        sub_end = w_end
        sentence_buffer = "".join(sub_text_parts)

    # Final sub-segment
    final_text = "".join(sub_text_parts).strip()
    if final_text:
        sub_segments.append({"start": sub_start, "end": sub_end, "text": final_text})

    return sub_segments


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
    # Long segments with word-level timestamps are split into shorter sentences.
    source_segments = []
    for i, seg in enumerate(asr_segments, start=1):
        sub_segs = split_segment_by_words(seg)
        for j, sub in enumerate(sub_segs, start=1):
            item = {
                "index": i if len(sub_segs) == 1 else i * 1000 + j,
                "start": sub.get("start"),
                "end": sub.get("end"),
                "text": sub.get("text", ""),
            }
            # Attach word-level timestamps to segments that were not split
            # (split segments don't carry per-word data to keep file size down)
            if len(sub_segs) == 1:
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
