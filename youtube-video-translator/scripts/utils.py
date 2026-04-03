import os
import shutil
import subprocess

def get_ffmpeg_path():
    """
    获取 FFmpeg 的最佳路径，优先选择具备完整能力的版本 (如 ffmpeg-full)。
    """
    # 候选路径列表
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # Apple Silicon Homebrew
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",     # Intel Homebrew
        shutil.which("ffmpeg-full"),
        shutil.which("ffmpeg")
    ]

    # 尝试寻找具备 libass 支持的 ffmpeg
    fallback = None
    seen = set()

    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)

        if os.path.exists(path):
            if check_libass_support(path):
                return path
            if not fallback:
                fallback = path

    # 如果没找到带 libass 的，回退到第一个可用的 ffmpeg
    return fallback

def get_ffprobe_path():
    """
    获取 FFprobe 的路径，优先选择与 FFmpeg 目录相同的版本。
    """
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        # 尝试寻找同目录下的 ffprobe
        from pathlib import Path
        sibling = Path(ffmpeg_path).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)

    # 回退到 PATH 中的 ffprobe
    return shutil.which("ffprobe")

def check_libass_support(ffmpeg_path):
    """
    检查指定路径的 ffmpeg 是否支持 libass。
    """
    if not ffmpeg_path:
        return False

    try:
        # 使用 -version 命令获取配置信息
        result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
        output = f"{result.stdout}\n{result.stderr}".lower()
        return "--enable-libass" in output or "libass" in output
    except Exception:
        return False
