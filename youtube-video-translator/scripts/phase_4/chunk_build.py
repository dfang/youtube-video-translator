#!/usr/bin/env python3
"""
Phase 4, Step 4a: Chunk Build

Reads temp/source_segments.json.
Splits into chunks based on time range + subtitle segment boundaries.
Outputs temp/chunks.json with per-chunk metadata.

Idempotent: skips if chunks.json already exists and source_segments unchanged.
"""
import json
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

LONG_VIDEO_THRESHOLD_SECONDS = 3600.0
LONG_VIDEO_MAX_CHUNK_DURATION = 30.0
DEFAULT_MAX_SEGMENTS_PER_CHUNK = 40
LONG_VIDEO_MAX_SEGMENTS_PER_CHUNK = 20


def compute_source_hash(source_file: Path) -> str:
    data = json.loads(source_file.read_text(encoding="utf-8"))
    return hashlib.sha256(
        json.dumps({"segments": data["segments"], "source": data["source"]}, sort_keys=True).encode()
    ).hexdigest()[:16]


def compute_glossary_hash(glossary_file: Path | None) -> str:
    if glossary_file is None or not glossary_file.exists():
        return "none"
    return hashlib.sha256(glossary_file.read_bytes()).hexdigest()[:16]


def seconds_to_srt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole_seconds = int(seconds)
    ms = int(round((seconds - whole_seconds) * 1000))
    if ms == 1000:
        whole_seconds += 1
        ms = 0
    h = whole_seconds // 3600
    m = (whole_seconds % 3600) // 60
    s = whole_seconds % 60
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def load_video_duration(temp_dir: Path) -> float:
    metadata_file = temp_dir / "metadata.json"
    if not metadata_file.exists():
        return 0.0
    try:
        payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        return float(payload.get("duration") or 0.0)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0.0


def is_chunks_fresh(temp_dir: Path, source_hash: str, glossary_hash: str) -> bool:
    chunks_file = temp_dir / "chunks.json"
    if not chunks_file.exists():
        return False
    try:
        data = json.loads(chunks_file.read_text(encoding="utf-8"))
        cfg = data.get("chunking_config", {})
        # If glossary changed, must rebuild
        if cfg.get("glossary_hash") != glossary_hash:
            return False
        if cfg.get("source_hash") != source_hash:
            return False
        return True
    except (json.JSONDecodeError, OSError):
        return False


def build_chunks(
    temp_dir: Path,
    max_chunk_duration: float = 60.0,
    max_tokens: int = 2000,
    strategy: str = "time_range_with_subtitle_boundary",
) -> tuple[int, str]:
    temp_dir = Path(temp_dir)
    source_file = temp_dir / "source_segments.json"

    if not source_file.exists():
        return 1, f"source_segments.json not found at {source_file}"

    # Check freshness
    source_hash = compute_source_hash(source_file)
    glossary_file = temp_dir / "glossary.json"
    glossary_hash = compute_glossary_hash(glossary_file)

    if is_chunks_fresh(temp_dir, source_hash, glossary_hash):
        print("[phase_4_chunk_build] chunks.json already fresh, skipping.")
        return 0, str(temp_dir / "chunks.json")

    source_data = json.loads(source_file.read_text(encoding="utf-8"))
    video_id = source_data.get("video_id", "")
    segments = source_data.get("segments", [])

    if not segments:
        return 1, "source_segments has no segments"

    video_duration = load_video_duration(temp_dir)
    adaptive_chunk_duration = max_chunk_duration
    adaptive_max_segments = DEFAULT_MAX_SEGMENTS_PER_CHUNK
    if video_duration >= LONG_VIDEO_THRESHOLD_SECONDS:
        adaptive_chunk_duration = min(max_chunk_duration, LONG_VIDEO_MAX_CHUNK_DURATION)
        adaptive_max_segments = LONG_VIDEO_MAX_SEGMENTS_PER_CHUNK

    # Load glossary terms if present
    glossary_terms = []
    if glossary_file.exists():
        try:
            glossary_data = json.loads(glossary_file.read_text(encoding="utf-8"))
            if isinstance(glossary_data, list):
                glossary_terms = glossary_data
        except (json.JSONDecodeError, OSError):
            pass

    # Chunking algorithm
    chunks = []
    current_chunk_segments = []
    current_chunk_start = None
    current_chunk_end = None
    current_chunk_text = ""

    def finalize_chunk(chunk_id: int, segs: list, start: float, end: float) -> dict:
        srt_blocks = []
        plain_lines = []
        for block_index, seg in enumerate(segs, start=1):
            seg_text = seg.get("text", "").strip()
            plain_lines.append(seg_text)
            srt_blocks.append(
                f"{block_index}\n"
                f"{seconds_to_srt(seg.get('start', 0.0))} --> {seconds_to_srt(seg.get('end', 0.0))}\n"
                f"{seg_text}"
            )
        text = "\n\n".join(srt_blocks).strip()
        return {
            "chunk_id": chunk_id,
            "segment_ids": [s.get("index", i + 1) for i, s in enumerate(segs)],
            "start": start,
            "end": end,
            "text": text,
            "source_plain_text": "\n".join(plain_lines).strip(),
            "source_block_count": len(segs),
            "status": "pending",
            "attempts": 0,
            "glossary_terms": glossary_terms,
            "error": None,
        }

    chunk_id = 1
    for i, seg in enumerate(segments):
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start)
        seg_text = seg.get("text", "")

        should_start_new = False
        if current_chunk_segments and current_chunk_start is not None:
            projected_duration = seg_end - current_chunk_start
            if strategy == "time_range_with_subtitle_boundary":
                if projected_duration > adaptive_chunk_duration:
                    should_start_new = True
            elif projected_duration >= adaptive_chunk_duration:
                should_start_new = True

            if len(current_chunk_segments) >= adaptive_max_segments:
                should_start_new = True

        if should_start_new:
            # Finalize current
            chunks.append(finalize_chunk(
                chunk_id,
                current_chunk_segments,
                current_chunk_start or seg_start,
                current_chunk_end or seg_end,
            ))
            chunk_id += 1
            current_chunk_segments = []
            current_chunk_start = None
            current_chunk_end = None
            current_chunk_text = ""

        # Add to current chunk
        if current_chunk_start is None:
            current_chunk_start = seg_start
        current_chunk_end = seg_end
        current_chunk_segments.append(seg)

    # Final chunk
    if current_chunk_segments:
        chunks.append(finalize_chunk(
            chunk_id,
            current_chunk_segments,
            current_chunk_start,
            current_chunk_end,
        ))

    chunks_data = {
        "video_id": video_id,
        "chunking_config": {
            "strategy": strategy,
            "max_chunk_duration": adaptive_chunk_duration,
            "max_segments_per_chunk": adaptive_max_segments,
            "max_tokens": max_tokens,
            "source_hash": source_hash,
            "glossary_hash": glossary_hash,
            "video_duration": video_duration,
        },
        "chunks": chunks,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    out_file = temp_dir / "chunks.json"
    out_file.write_text(json.dumps(chunks_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_4_chunk_build] chunks.json written: {len(chunks)} chunks from {len(segments)} segments")
    return 0, str(out_file)


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_chunk_build.py [TempDir] [MaxChunkDuration秒] [MaxTokens] [Strategy]")
        sys.exit(1)

    temp_dir = Path(sys.argv[1])
    max_duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    max_tokens = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
    strategy = sys.argv[4] if len(sys.argv) > 4 else "time_range_with_subtitle_boundary"

    exit_code, msg = build_chunks(temp_dir, max_duration, max_tokens, strategy)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
