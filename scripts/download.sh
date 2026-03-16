#!/bin/bash
# Download YouTube video and subtitles
# Usage: ./download.sh <URL> <TARGET_LANG> <SUBTITLE_SOURCE>
# SUBTITLE_SOURCE: download (default) or whisper
#   - download: 下载 YouTube 英文字幕
#   - whisper:  不下载字幕，后续使用本地 Whisper 重新生成

set -e

VIDEO_URL="$1"
TARGET_LANG="${2:-zh-CN}"
SUBTITLE_SOURCE="${3:-download}"  # download or whisper

# Get video title for filename
echo "  获取视频信息..."
VIDEO_TITLE=$(yt-dlp --get-title "$VIDEO_URL" 2>/dev/null || echo "video")

# Sanitize filename
SAFE_TITLE=$(echo "$VIDEO_TITLE" | tr -d '\/:*?"<>|' | cut -c1-50)

echo "  视频标题：$VIDEO_TITLE"
echo "  保存名称：$SAFE_TITLE"

# Download video
echo "  下载视频..."
yt-dlp \
    --cookies-from-browser=chrome \
    --remote-components ejs:npm \
    -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
    --output "$SAFE_TITLE.original.%(ext)s" \
    "$VIDEO_URL"

# Download subtitles based on source preference
echo "  字幕来源：$SUBTITLE_SOURCE"
if [[ "$SUBTITLE_SOURCE" == "whisper" ]]; then
    echo "  跳过字幕下载，后续将使用 Whisper 本地转录（无高亮，时间轴更干净）"
else
    # Download English subtitles only (non-highlighted)
    echo "  下载英文字幕（使用 yt-dlp 下载原始字幕，无逐词高亮）..."
    yt-dlp \
        --cookies-from-browser=chrome \
        --write-auto-sub \
        --write-sub \
        --sub-lang "en" \
        --skip-download \
        --sub-format "vtt" \
        --output "$SAFE_TITLE.%(ext)s" \
        "$VIDEO_URL" || echo "  警告：未找到英文字幕"
fi

# Extract audio for voice cloning
echo "  提取音频..."
yt-dlp \
    --cookies-from-browser=chrome \
    -x \
    --audio-format mp3 \
    --output "$SAFE_TITLE.audio.%(ext)s" \
    "$VIDEO_URL"

echo "✅ 下载完成"
