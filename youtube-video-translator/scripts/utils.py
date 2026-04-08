import os
import re
import json
import shutil
import subprocess
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone

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

        if os.path.exists(str(path)):
            if check_libass_support(path):
                return str(path)
            if not fallback:
                fallback = str(path)

    # 如果没找到带 libass 的，回退到第一个可用的 ffmpeg
    return fallback

def get_ffprobe_path():
    """
    获取 FFprobe 的路径，优先选择与 FFmpeg 目录相同的版本。
    """
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        # 尝试寻找同目录下的 ffprobe
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

def get_video_dir(video_id: str) -> Path:
    # 优先使用环境变量 TRANS_ROOT，如果没有设置，则默认使用 ~/Videos/translations
    root = os.environ.get("TRANS_ROOT")
    if root:
        return Path(root) / "translations" / video_id

    # 默认路径：~/Videos/translations
    default_root = Path.home() / "Videos" / "translations"
    return default_root / video_id

def get_temp_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "temp"

def get_final_dir(video_id: str) -> Path:
    return get_video_dir(video_id) / "final"

def ensure_dirs(video_id: str) -> None:
    get_temp_dir(video_id).mkdir(parents=True, exist_ok=True)
    get_final_dir(video_id).mkdir(parents=True, exist_ok=True)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def run_subprocess(
    cmd: list[str],
    heartbeat_phase: int | None = None,
    heartbeat_name: str | None = None,
    heartbeat_interval: int = 60,
) -> tuple[int, str]:
    if heartbeat_phase is None or heartbeat_name is None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stream:
        process = subprocess.Popen(cmd, stdout=stream, stderr=stream, text=True)
        started_at = time.monotonic()
        last_heartbeat = started_at

        while True:
            try:
                returncode = process.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_interval:
                    elapsed = int(now - started_at)
                    print(f"[Phase {heartbeat_phase}/10][HEARTBEAT] {heartbeat_name} | elapsed: {elapsed}s")
                    last_heartbeat = now

        stream.seek(0)
        output = stream.read().strip()
        return returncode, output

def parse_srt_blocks(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    blocks = re.split(r"\n\s*\n", content)
    parsed = []
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines()]
        if len(lines) < 3:
            continue
        parsed.append(
            {
                "index": lines[0].strip(),
                "timecode": lines[1].strip(),
                "text": "\n".join(lines[2:]).strip(),
            }
        )
    return parsed

def write_srt_blocks(path: Path, blocks: list[dict]) -> None:
    rendered = []
    for block in blocks:
        rendered.append(f"{block['index']}\n{block['timecode']}\n{block['text']}")
    path.write_text("\n\n".join(rendered) + ("\n" if rendered else ""), encoding="utf-8")

def _seconds_to_srt(secs: float) -> str:
    """Convert float seconds to SRT timestamp: 00:00:00,000"""
    secs = max(0, secs)
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        normalized = " ".join(item.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

def shorten_text(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."

def target_is_fresh(target: Path, sources: list[Path]) -> bool:
    if not target.exists():
        return False
    target_mtime = target.stat().st_mtime
    for source in sources:
        if source.exists() and source.stat().st_mtime > target_mtime:
            return False
    return True
