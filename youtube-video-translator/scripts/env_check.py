import sys
from utils import get_ffmpeg_path, check_libass_support

def check_python_packages():
    missing = []
    packages = ["pysubs2", "PIL", "whisperx", "yt_dlp"]
    for p in packages:
        try:
            if p == "PIL":
                import PIL
            else:
                __import__(p)
        except ImportError:
            missing.append(p)
    return missing

def run_checks():
    print("--- Environment Self-Check (Standardized) ---")
    
    # 1. Check FFmpeg
    ffmpeg_path = get_ffmpeg_path()
    libass_ok = check_libass_support(ffmpeg_path) if ffmpeg_path else False
    
    print(f"[*] FFmpeg Path: {ffmpeg_path or 'Not Found'}")
    if libass_ok:
        print(f"[*] FFmpeg Capability: Found 'libass' support.")
    else:
        print(f"[!] FFmpeg Capability: 'libass' NOT found. Hardcoding subtitles will fail.")
    
    # 2. Check Python Packages
    missing = check_python_packages()
    if missing:
        print(f"[!] Missing Python packages: {', '.join(missing)}")
        print(f"    Fix: pip install -r youtube-video-translator/requirements.txt")
    else:
        print("[*] Python dependencies: All present.")
        
    # 3. Summary
    if ffmpeg_path and libass_ok and not missing:
        print("\n[SUCCESS] Environment is ready.")
        return True
    else:
        print("\n[FAILURE] Environment check failed.")
        return False

if __name__ == "__main__":
    if not run_checks():
        sys.exit(1)
