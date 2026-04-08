#!/usr/bin/env python3
"""
Phase 4, Step 5a: Align

Reads temp/source_segments.json and temp/chunks.json.
Maps translated chunk text back to original segments.
Outputs temp/subtitle_manifest.json (canonical subtitle artifact).

Time轴不可丢失: start/end must match source_segments exactly (error < 0.1s).
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def is_manifest_fresh(temp_dir: Path) -> bool:
    f = temp_dir / "subtitle_manifest.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return len(data.get("segments", [])) > 0
    except (json.JSONDecodeError, OSError):
        return False


def load_source_segments(temp_dir: Path) -> dict:
    return json.loads((temp_dir / "source_segments.json").read_text(encoding="utf-8"))


def load_chunks(temp_dir: Path) -> dict:
    return json.loads((temp_dir / "chunks.json").read_text(encoding="utf-8"))


def load_translated_chunk(chunk_id: int, temp_dir: Path) -> str:
    f = temp_dir / f"chunk_{chunk_id}.translated.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return ""


def align(temp_dir: Path, layout: str = "bilingual") -> tuple[int, str]:
    temp_dir = Path(temp_dir)

    if is_manifest_fresh(temp_dir):
        print("[phase_4_align] subtitle_manifest.json already fresh, skipping.")
        return 0, str(temp_dir / "subtitle_manifest.json")

    source_data = load_source_segments(temp_dir)
    chunks_data = load_chunks(temp_dir)
    source_segments = source_data.get("segments", [])
    chunks = chunks_data.get("chunks", [])

    if not source_segments:
        return 1, "source_segments has no segments"

    # Build a lookup: segment_id -> source segment
    seg_map = {seg.get("index", i + 1): seg for i, seg in enumerate(source_segments)}

    manifest_segments = []
    alignment_errors = []

    for chunk in chunks:
        if chunk.get("status") != "completed":
            continue
        chunk_id = chunk["chunk_id"]
        segment_ids = chunk.get("segment_ids", [])
        translated_text = load_translated_chunk(chunk_id, temp_dir)

        # Split translated text by SRT block (each block separated by blank line)
        # Parse translated SRT
        translated_blocks = _parse_translated_srt(translated_text)
        if len(translated_blocks) != len(segment_ids):
            alignment_errors.append(
                {
                    "chunk_id": chunk_id,
                    "expected_blocks": len(segment_ids),
                    "actual_blocks": len(translated_blocks),
                    "error": "translated block count mismatch",
                }
            )
            continue

        # Map each source segment to translated
        for i, seg_id in enumerate(segment_ids):
            source_seg = seg_map.get(seg_id)
            if source_seg is None:
                alignment_errors.append(
                    {
                        "chunk_id": chunk_id,
                        "segment_id": seg_id,
                        "error": "source segment missing during align",
                    }
                )
                continue

            trans_text = translated_blocks[i].get("text", "")
            if not trans_text.strip():
                alignment_errors.append(
                    {
                        "chunk_id": chunk_id,
                        "segment_id": seg_id,
                        "error": "empty translated text during align",
                    }
                )
                continue

            manifest_segments.append({
                "segment_id": seg_id,
                "start": source_seg.get("start"),
                "end": source_seg.get("end"),
                "source_text": source_seg.get("text", ""),
                "translated_text": trans_text,
            })

    if alignment_errors:
        err_file = temp_dir / "alignment_errors.json"
        err_file.write_text(
            json.dumps(
                {
                    "errors": alignment_errors,
                    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1, f"alignment failed; details written to {err_file}"

    # Sort by start time
    manifest_segments.sort(key=lambda s: s.get("start", 0))

    manifest_data = {
        "video_id": source_data.get("video_id", ""),
        "layout": layout,
        "segments": manifest_segments,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    out_file = temp_dir / "subtitle_manifest.json"
    out_file.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_4_align] subtitle_manifest.json written: {len(manifest_segments)} segments")
    return 0, str(out_file)


def _parse_translated_srt(text: str) -> list[dict]:
    """Parse translated SRT text into list of {index, start, end, text}."""
    import re
    blocks = re.split(r"\n\s*\n", text.strip())
    time_re = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")
    parsed = []

    for block in blocks:
        lines = [l.rstrip("\r") for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        tm = time_re.search(lines[1])
        if not tm:
            continue
        parsed.append({
            "index": int(lines[0].strip()),
            "start": tm.group(1),
            "end": tm.group(2),
            "text": "\n".join(lines[2:]).strip(),
        })
    return parsed


def main():
    if len(sys.argv) < 2:
        print("Usage: phase_4_align.py [TempDir] [Layout:bilingual|chinese_only]")
        sys.exit(1)
    temp_dir = Path(sys.argv[1])
    layout = sys.argv[2] if len(sys.argv) > 2 else "bilingual"
    exit_code, msg = align(temp_dir, layout)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
