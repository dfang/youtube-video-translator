#!/usr/bin/env python3
"""
Phase 4, Step 1: Caption Fetch (Official)

Official caption path: uses yt-dlp to download English subtitles.
Normalizes to temp/source_segments.json (not asr_segments).

Idempotent: skips if source_segments.json already exists and matches caption_plan.
"""
import json
import re
import subprocess
import sys
import hashlib
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/phase_3"))

from yt_dlp_cookies import detect_browser_cookie_args


def normalize_timestamp(ts: str) -> str:
    """Convert various SRT timestamp formats to uniform float seconds."""
    ts = ts.strip()
    # SRT format: 00:00:00,000 or 00:00:00.000
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, rest = parts
        sec, ms = rest.split(".")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0
    return 0.0


def parse_srt_segments(srt_text: str) -> list[dict]:
    """Parse SRT content into list of {start, end, text} dicts."""
    # Split into blocks
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    segments = []
    time_re = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")

    for block in blocks:
        lines = [l.rstrip("\r") for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        # Line 0 = index, Line 1 = timecode, Rest = text
        time_match = time_re.search(lines[1])
        if not time_match:
            continue
        segments.append({
            "index": int(lines[0].strip()),
            "start": normalize_timestamp(time_match.group(1)),
            "end": normalize_timestamp(time_match.group(2)),
            "text": "\n".join(lines[2:]).strip(),
        })
    return segments


def srt_segments_to_json(segments: list, video_id: str) -> dict:
    return {
        "video_id": video_id,
        "source": "official",
        "language": "en",
        "segments": segments,
        "generated_at": "",  # filled by caller
    }


def is_source_segments_fresh(temp_dir: Path) -> bool:
    """Check if source_segments.json already exists for official caption path."""
    f = temp_dir / "source_segments.json"
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("source") == "official"
    except (json.JSONDecodeError, OSError):
        return False


def caption_fetch(temp_dir: Path, url: str) -> tuple[int, str]:
    """
    Download official English subtitles via yt-dlp.
    Normalize and write to temp/source_segments.json.
    """
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    if is_source_segments_fresh(temp_dir):
        print("[phase_4_caption_fetch] source_segments.json (official) already fresh, skipping.")
        return 0, str(temp_dir / "source_segments.json")

    cookie_args, cookie_probe_error = detect_browser_cookie_args("chrome")
    if cookie_probe_error:
        print(
            "[phase_4_caption_fetch] browser cookie probe failed; "
            f"continuing without browser cookies. stderr/stdout: {cookie_probe_error}"
        )

    # Download en subtitles only
    subtitle_template = str(temp_dir / "en_official")
    print(f"[phase_4_caption_fetch] Fetching official English subtitles for {url}...")
    result = subprocess.run(
        [
            "yt-dlp", "--skip-download",
            "--write-subs", "--sub-langs", "en.*",
            "--convert-subs", "srt",
            *cookie_args,
            "-o", subtitle_template,
            url,
        ],
        capture_output=True,
        text=True,
    )

    # yt-dlp exits 0 even if no subs found — check for file
    srt_files = sorted(temp_dir.glob("en_official.*.srt"))
    if not srt_files:
        # Try fallback glob
        srt_files = sorted(temp_dir.glob("*en*.srt"))

    if not srt_files:
        detail = (result.stderr or result.stdout or "").strip()[:1000]
        if cookie_probe_error:
            detail = f"{detail}\n[browser-cookie-probe] {cookie_probe_error}" if detail else cookie_probe_error
        return 1, f"No English subtitles found. yt-dlp stderr/stdout: {detail}"

    srt_file = srt_files[0]
    srt_text = srt_file.read_text(encoding="utf-8")
    segments = parse_srt_segments(srt_text)

    if not segments:
        return 1, f"Downloaded SRT at {srt_file} but found no valid segments"

    video_id = ""
    metadata_file = temp_dir / "metadata.json"
    if metadata_file.exists():
        try:
            video_id = json.loads(metadata_file.read_text(encoding="utf-8")).get("video_id", "")
        except (json.JSONDecodeError, OSError):
            pass

    from datetime import datetime, timezone
    manifest = srt_segments_to_json(segments, video_id)
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    out_file = temp_dir / "source_segments.json"
    out_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[phase_4_caption_fetch] source_segments.json written: {len(segments)} segments from {srt_file.name}")
    return 0, str(out_file)


def main():
    if len(sys.argv) < 3:
        print("Usage: phase_4_caption_fetch.py [URL] [TempDir]")
        sys.exit(1)
    url = sys.argv[1]
    temp_dir = Path(sys.argv[2])
    exit_code, msg = caption_fetch(temp_dir, url)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
