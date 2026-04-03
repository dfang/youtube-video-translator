import os
import sys
import subprocess
import json

def download_video(url, output_dir):
    """
    使用 yt-dlp 下载视频、元数据和官方字幕。
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 1. 获取视频信息 (JSON)
    info_path = os.path.join(output_dir, "video.info.json")
    print(f"正在获取视频信息: {url}...")
    subprocess.run([
        "yt-dlp", "--skip-download", "--write-info-json",
        "--cookies-from-browser", "chrome",
        "-o", os.path.join(output_dir, "video"), url
    ], check=True)

    # 2. 下载原始视频 (优先选择 1080p mp4)
    video_path = os.path.join(output_dir, "raw_video.mp4")
    if not os.path.exists(video_path):
        print("正在下载原始视频...")
        subprocess.run([
            "yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--cookies-from-browser", "chrome",
            "-o", video_path, url
        ], check=True)
    else:
        print("原始视频已存在，跳过下载。")

    # 3. 尝试下载官方英文字幕 (srt)
    print("正在检查官方字幕...")
    subprocess.run([
        "yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "en.*",
        "--cookies-from-browser", "chrome",
        "--convert-subs", "srt", "-o", os.path.join(output_dir, "en_official"), url
    ])

    return video_path

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python downloader.py [URL] [OutputDir]")
        sys.exit(1)

    video_url = sys.argv[1]
    out_dir = sys.argv[2]
    download_video(video_url, out_dir)
