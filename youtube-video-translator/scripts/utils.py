import os
import shutil
import subprocess

def get_ffmpeg_path():
    """
    获取 FFmpeg 的最佳路径，优先选择具备完整能力的版本。
    """
    # 明确的高优先级路径 (针对 macOS Homebrew ffmpeg-full)
    priority_paths = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/bin/ffmpeg"
    ]
    
    for path in priority_paths:
        if os.path.exists(path):
            return path
            
    # 如果明确路径不存在，尝试在 PATH 中寻找
    # 注意：某些环境可能通过别名或软链设置了 ffmpeg-full
    return shutil.which("ffmpeg-full") or shutil.which("ffmpeg")

def check_libass_support(ffmpeg_path):
    if not ffmpeg_path:
        return False

    try:
        result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True)
        output = f"{result.stdout}\n{result.stderr}".lower()
        return "libass" in output
    except Exception:
        return False
