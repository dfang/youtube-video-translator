#!/usr/bin/env python3
"""
Phase 3, Step 3: Raw Video Download

Downloads the raw video via yt-dlp.
Outputs temp/raw_video.mp4.

Idempotent: skips if raw_video.mp4 already exists.
"""
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from yt_dlp_cookies import detect_browser_cookie_args


def is_video_fresh(temp_dir: Path) -> bool:
    video_file = temp_dir / "raw_video.mp4"
    url_file = temp_dir / "url.txt"
    if not video_file.exists():
        return False
    # If url.txt changed since video was downloaded, redownload
    if url_file.exists() and video_file.exists():
        video_mtime = video_file.stat().st_mtime
        url_mtime = url_file.stat().st_mtime
        if url_mtime > video_mtime:
            return False
    return True


def download_video(url: str, temp_dir: Path) -> tuple[int, str]:
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    video_file = temp_dir / "raw_video.mp4"

    cookie_args, cookie_probe_error = detect_browser_cookie_args("chrome")
    if cookie_probe_error:
        print(
            "[phase_3_video_download] browser cookie probe failed; "
            f"continuing without browser cookies. stderr/stdout: {cookie_probe_error}"
        )

    print(f"[phase_3_video_download] Downloading video to {video_file}...")

    # 720p mp4 to save bandwidth — 1080p+ only if necessary
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        *cookie_args,
        "-o", str(video_file),
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:1000]
        if cookie_probe_error:
            detail = f"{detail}\n[browser-cookie-probe] {cookie_probe_error}" if detail else cookie_probe_error
        return result.returncode, f"yt-dlp download failed: {detail}"

    if not video_file.exists():
        return 1, f"yt-dlp exited 0 but {video_file} was not created"

    size_mb = video_file.stat().st_size / (1024 * 1024)
    print(f"[phase_3_video_download] Download complete: {video_file} ({size_mb:.1f} MB)")
    return 0, str(video_file)


def main():
    if len(sys.argv) < 3:
        print("Usage: phase_3_video_download.py [URL] [TempDir]")
        sys.exit(1)

    url = sys.argv[1]
    temp_dir = Path(sys.argv[2])

    if is_video_fresh(temp_dir):
        print(f"[phase_3_video_download] raw_video.mp4 already fresh, skipping.")
        sys.exit(0)

    exit_code, msg = download_video(url, temp_dir)
    print(msg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
