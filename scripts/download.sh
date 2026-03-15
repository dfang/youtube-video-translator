#!/bin/bash
# Download YouTube video and subtitles
# Usage: ./download.sh <URL> <TARGET_LANG>

set -e

VIDEO_URL="$1"
TARGET_LANG="${2:-zh-CN}"

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

# Download subtitles (all available languages)
echo "  下载字幕..."
yt-dlp \
    --cookies-from-browser=chrome \
    --write-auto-sub \
    --write-sub \
    --sub-lang "en,zh-Hans,zh-Hant,zh" \
    --skip-download \
    --output "$SAFE_TITLE.%(ext)s" \
    "$VIDEO_URL" || echo "  警告：未找到字幕，后续将自动转录"

# Extract audio for voice cloning
echo "  提取音频..."
yt-dlp \
    --cookies-from-browser=chrome \
    -x \
    --audio-format mp3 \
    --output "$SAFE_TITLE.audio.%(ext)s" \
    "$VIDEO_URL"

echo "✅ 下载完成"
