import os
import sys
import subprocess
import shutil

# 优先使用 ffmpeg-full（包含 libass，支持烧录字幕）
FFMPEG = shutil.which("ffmpeg-full") or shutil.which("ffmpeg") or "ffmpeg"

def create_muxed_video(video_path, audio_path, ass_path, output_dir, use_original_audio=False):
    """
    使用 FFmpeg 合成最终视频。
    1. 若 use_original_audio 为 False，则替换音轨。
    2. 烧录 .ass 字幕。
    输出固定为 {output_dir}/final/final_video.mp4
    """
    final_dir = os.path.join(output_dir, "final")
    os.makedirs(final_dir, exist_ok=True)
    final_output = os.path.join(final_dir, "final_video.mp4")

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
    if len(sys.argv) < 5:
        print("用法: python video_muxer.py [VideoPath] [AudioPath] [AssPath] [OutputPath] [--original-audio]")
        sys.exit(1)

    v_path = sys.argv[1]
    a_path = sys.argv[2]
    sub_path = sys.argv[3]
    out_dir = sys.argv[4]
    use_original = "--original-audio" in sys.argv

    create_muxed_video(v_path, a_path, sub_path, out_dir, use_original)
