import os
import sys
import subprocess
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

from utils import get_ffmpeg_path

FFMPEG = get_ffmpeg_path()

def _resolve_final_output_path(output_target):
    """
    兼容两种调用方式：
    1) 目录模式（推荐）:
       - 传入项目根目录: ./translations/[VIDEO_ID]
       - 输出: ./translations/[VIDEO_ID]/final/final_video.mp4
       - 传入 final 目录: ./translations/[VIDEO_ID]/final
       - 输出: ./translations/[VIDEO_ID]/final/final_video.mp4
    2) 文件模式（兼容旧调用）:
       - 传入完整文件路径: ./translations/[VIDEO_ID]/final/final_video.mp4
       - 输出: 原路径
    """
    normalized = os.path.normpath(output_target)

    if normalized.lower().endswith(".mp4"):
        return normalized

    if os.path.basename(normalized) == "final":
        return os.path.join(normalized, "final_video.mp4")

    return os.path.join(normalized, "final", "final_video.mp4")


def create_muxed_video(video_path, audio_path, ass_path, output_target, use_original_audio=False):
    """
    使用 FFmpeg 合成最终视频。
    1. 若 use_original_audio 为 False，则替换音轨。
    2. 烧录 .ass 字幕。
    输出路径兼容目录/文件两种传参，详见 _resolve_final_output_path。
    """
    final_output = _resolve_final_output_path(output_target)
    final_dir = os.path.dirname(final_output)
    os.makedirs(final_dir, exist_ok=True)

    if not FFMPEG:
        raise RuntimeError("FFmpeg not found. Please install ffmpeg/ffmpeg-full and retry.")

    # 基本命令构建
    ffmpeg_cmd = [FFMPEG, "-i", video_path]

    if not use_original_audio and audio_path and os.path.exists(audio_path):
        # 替换为中文配音
        ffmpeg_cmd += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        # 保留原音
        ffmpeg_cmd += ["-map", "0:v:0", "-map", "0:a:0"]

    # 视频滤镜：烧录 .ass 字幕
    # 注意：在 FFmpeg 的 subtitles 滤镜中，路径需要转义
    # 例如：subtitles='output/temp/bilingual.ass'
    # 对于 macOS/Linux，简单的引号即可
    filter_complex = f"subtitles='{ass_path}'"
    ffmpeg_cmd += ["-vf", filter_complex]

    # 编码设置：优先选择高质量编码器 (libx264)
    # 对于 M4，你可以考虑使用 h264_videotoolbox 进行硬件加速，但 libx264 兼容性最强
    ffmpeg_cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        final_output, "-y"
    ]

    print(f"正在合成视频: {' '.join(ffmpeg_cmd)}")
    subprocess.run(ffmpeg_cmd, check=True)
    print(f"合成完成: {final_output}")

if __name__ == "__main__":
    # 支持两种调用方式：
    # 1) 位置参数（直接调用）: video_muxer.py [VideoPath] [AudioPath] [AssPath] [OutputTarget] [--original-audio]
    # 2) 命名参数（phase_runner 调用）: video_muxer.py --video-id ID --temp-dir DIR --final-dir DIR --layout LAYOUT [--original-audio]
    args = sys.argv[1:]

    # 检测是否为命名参数模式
    if args and args[0].startswith("--"):
        # 命名参数模式
        if "--video-id" not in args and "--temp-dir" not in args:
            print("用法: video_muxer.py --video-id ID --temp-dir DIR --final-dir DIR --layout LAYOUT [--original-audio]")
            sys.exit(1)

        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--video-id", required=True)
        parser.add_argument("--temp-dir", required=True)
        parser.add_argument("--final-dir", required=True)
        parser.add_argument("--layout", default="bilingual")
        parser.add_argument("--original-audio", action="store_true")
        parsed = parser.parse_args(args)

        video_id = parsed.video_id
        temp_dir = Path(parsed.temp_dir)
        final_dir = Path(parsed.final_dir)
        layout = parsed.layout
        use_original = parsed.original_audio

        video_path = str(temp_dir / "raw_video.mp4")
        ass_path = str(temp_dir / ("bilingual.ass" if layout == "bilingual" else "zh_only.ass"))
        output_target = str(final_dir)
    else:
        # 位置参数模式
        if len(sys.argv) < 5:
            print("用法: python video_muxer.py [VideoPath] [AudioPath] [AssPath] [OutputTarget] [--original-audio]")
            print("OutputTarget 可传项目目录、final 目录或最终 .mp4 文件路径")
            sys.exit(1)

        v_path = sys.argv[1]
        a_path = sys.argv[2]
        sub_path = sys.argv[3]
        out_target = sys.argv[4]
        use_original = "--original-audio" in sys.argv

        video_path = v_path
        ass_path = sub_path
        output_target = out_target

    create_muxed_video(video_path, None, ass_path, output_target, use_original)
