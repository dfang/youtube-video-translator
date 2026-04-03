import os
import shutil
import sys
from pathlib import Path

from utils import check_libass_support, get_ffmpeg_path


def check_python_packages():
    missing = []
    packages = [
        ("pysubs2", "pysubs2"),
        ("PIL", "Pillow"),
        ("whisperx", "whisperx"),
        ("yt_dlp", "yt-dlp"),
        ("requests", "requests"),
        ("edge_tts", "edge-tts"),
    ]
    for import_name, package_name in packages:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package_name)
    return missing


def check_cli_tools(ffmpeg_path):
    missing = []
    tools = {
        "yt-dlp": shutil.which("yt-dlp"),
        "curl": shutil.which("curl"),
    }

    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path and ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name("ffprobe")
        if sibling.exists():
            ffprobe_path = str(sibling)
    tools["ffprobe"] = ffprobe_path

    for name, path in tools.items():
        if not path:
            missing.append(name)

    return missing, tools


def find_chrome_cookie_db():
    candidates = [
        Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies",
        Path.home() / "Library/Application Support/Google/Chrome/Profile 1/Cookies",
        Path.home() / ".config/google-chrome/Default/Cookies",
        Path.home() / ".config/google-chrome/Profile 1/Cookies",
        Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Cookies",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def run_checks():
    print("--- Environment Self-Check (Standardized) ---")

    ffmpeg_path = get_ffmpeg_path()
    libass_ok = check_libass_support(ffmpeg_path) if ffmpeg_path else False
    missing_packages = check_python_packages()
    missing_tools, tool_paths = check_cli_tools(ffmpeg_path)
    chrome_cookie_db = find_chrome_cookie_db()

    print(f"[*] FFmpeg Path: {ffmpeg_path or 'Not Found'}")
    if libass_ok:
        print("[*] FFmpeg Capability: Found 'libass' support. (支持硬字幕烧录)")
    else:
        print("[!] FFmpeg Capability: 'libass' NOT found. Hardcoding subtitles will fail.")
        print("[!] 提示: 当前 FFmpeg 编译时未包含 libass，无法烧录硬字幕。")
        print("    Fix: brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass")
        print("    Or: brew install ffmpeg-full")

    if missing_packages:
        print(f"[!] Missing Python packages: {', '.join(missing_packages)}")
        print("    Fix: pip install -r youtube-video-translator/requirements.txt")
    else:
        print("[*] Python dependencies: All present.")

    for name in ("yt-dlp", "curl", "ffprobe"):
        path = tool_paths.get(name)
        print(f"[*] Tool {name}: {path or 'Not Found'}")
    if missing_tools:
        print(f"[!] Missing CLI tools: {', '.join(missing_tools)}")

    if chrome_cookie_db:
        print(f"[*] Chrome cookie source: {chrome_cookie_db}")
    else:
        print("[!] Chrome cookie source: Not found. Downloader currently requires --cookies-from-browser chrome.")

    print("[*] Phase 9 note: Browser automation still requires a logged-in interactive browser session.")

    failed = bool(
        (not ffmpeg_path)
        or (not libass_ok)
        or missing_packages
        or missing_tools
        or (chrome_cookie_db is None)
    )

    if failed:
        print("\n[FAILURE] Environment check failed.")
        return False

    print("\n[SUCCESS] Environment is ready.")
    return True


if __name__ == "__main__":
    if not run_checks():
        sys.exit(1)
