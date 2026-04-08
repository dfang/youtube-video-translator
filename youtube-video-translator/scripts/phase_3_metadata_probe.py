#!/usr/bin/env python3
"""
Phase 3, Step 1: Metadata Probe

Calls yt-dlp --write-info-json to extract video metadata.
Outputs temp/metadata.json with the required schema fields.

Idempotent: skips if metadata.json already exists and is valid.
"""
import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_ROOT / "schemas" / "metadata.schema.json"

# sys.path manipulation for state_manager (used by phase_runner convention)
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from yt_dlp_cookies import detect_browser_cookie_args


def compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def is_metadata_fresh(temp_dir: Path) -> bool:
    """Check if metadata.json exists and info_json is newer."""
    metadata_file = temp_dir / "metadata.json"
    info_file = temp_dir / "video.info.json"
    if not metadata_file.exists():
        return False
    # If video.info.json is newer than metadata.json, metadata is stale
    if info_file.exists() and info_file.stat().st_mtime > metadata_file.stat().st_mtime:
        return False
    # Validate basic required fields
    try:
        data = json.loads(metadata_file.read_text(encoding="utf-8"))
        for field in ("video_id", "title", "duration", "has_official_caption", "caption_languages"):
            if field not in data:
                return False
        return True
    except (json.JSONDecodeError, OSError):
        return False


def probe_metadata(url: str, temp_dir: Path) -> tuple[int, str]:
    """
    Run yt-dlp --skip-download --write-info-json to extract metadata.
    Then extract has_official_caption and caption_languages.
    Returns (exit_code, message).
    """
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    info_file = temp_dir / "video.info.json"

    cookie_args, cookie_probe_error = detect_browser_cookie_args("chrome")
    if cookie_probe_error:
        print(
            "[phase_3_metadata_probe] browser cookie probe failed; "
            f"continuing without browser cookies. stderr/stdout: {cookie_probe_error}"
        )

    print(f"[phase_3_metadata_probe] Probing metadata for {url}...")
    result = subprocess.run(
        ["yt-dlp", "--skip-download", "--write-info-json", "-o", str(temp_dir / "video"), *cookie_args, url],
        capture_output=True,
        text=True,
    )
    exit_code = result.returncode

    if exit_code != 0:
        detail = (result.stderr or result.stdout or "").strip()[:1000]
        if cookie_probe_error:
            detail = f"{detail}\n[browser-cookie-probe] {cookie_probe_error}" if detail else cookie_probe_error
        return exit_code, f"yt-dlp metadata probe failed: {detail}"

    if not info_file.exists():
        return 1, f"yt-dlp did not produce {info_file}"

    # Parse info_json
    try:
        info = json.loads(info_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 1, f"video.info.json is not valid JSON"

    # Build metadata.json with required fields
    # yt-dlp caption languages: info.get('automatic_captions') = {lang: [url,...]}
    #                         info.get('subtitles') = {lang: [url,...]}
    has_official_caption = bool(info.get("subtitles") or info.get("automatic_captions"))

    caption_languages = list(
        set(
            list(info.get("subtitles", {}).keys())
            + list(info.get("automatic_captions", {}).keys())
        )
    )

    metadata = {
        "video_id": info.get("id", ""),
        "title": info.get("title", ""),
        "duration": info.get("duration") or 0,
        "has_official_caption": has_official_caption,
        "caption_languages": caption_languages,
        # Preserve full info as additional data
        "uploader": info.get("uploader") or info.get("channel"),
        "channel": info.get("channel"),
        "fulltitle": info.get("fulltitle"),
    }

    metadata_file = temp_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[phase_3_metadata_probe] metadata.json written: "
        f"video_id={metadata['video_id']} has_caption={has_official_caption} "
        f"languages={caption_languages}"
    )
    return 0, str(metadata_file)


def main():
    if len(sys.argv) < 3:
        print("Usage: phase_3_metadata_probe.py [URL] [TempDir]")
        sys.exit(1)
    url = sys.argv[1]
    temp_dir = Path(sys.argv[2])

    # Idempotency check
    if is_metadata_fresh(temp_dir):
        print(f"[phase_3_metadata_probe] metadata.json already fresh, skipping.")
        sys.exit(0)

    exit_code, msg = probe_metadata(url, temp_dir)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
