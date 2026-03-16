#!/bin/bash
# Download YouTube video and subtitles
# Usage: ./download.sh <VIDEO_URL> <TARGET_LANG> <SUBTITLE_SOURCE> <WORK_DIR>
# SUBTITLE_SOURCE: download (default), whisper, or whisperx
#   - download: 下载 YouTube 英文字幕
#   - whisper:  不下载字幕，后续使用本地 Whisper 重新生成
#   - whisperx: 不下载字幕，后续使用 faster-whisper + whisperx 对齐

set -e

VIDEO_URL="$1"
TARGET_LANG="${2:-zh-CN}"
SUBTITLE_SOURCE="${3:-download}"  # download, whisper, or whisperx
WORK_DIR="${4:-}"  # Optional: use provided work dir, otherwise auto-detect

# Get video ID for directory name
VIDEO_ID=$(yt-dlp --get-id "$VIDEO_URL" 2>/dev/null || echo "unknown")

# If WORK_DIR not provided, use default videos/VIDEO_ID
if [[ -z "$WORK_DIR" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BASE_DIR="$(dirname "$SCRIPT_DIR")"
    WORK_DIR="$BASE_DIR/videos/$VIDEO_ID"
fi

mkdir -p "$WORK_DIR"

# Get video title for filename
echo "  获取视频信息..."
VIDEO_TITLE=$(yt-dlp --get-title "$VIDEO_URL" 2>/dev/null || echo "video")

# Sanitize filename - remove newlines and special chars, limit length
SAFE_TITLE=$(echo "$VIDEO_TITLE" | tr '\n' ' ' | tr -d '\/:*?"<>|' | sed 's/  */ /g' | cut -c1-50)

echo "  视频标题：$VIDEO_TITLE"
echo "  保存目录：$WORK_DIR"

# Download video
echo "  下载视频..."
yt-dlp \
    --cookies-from-browser=chrome \
    --remote-components ejs:npm \
    -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
    --output "$WORK_DIR/$SAFE_TITLE.original.%(ext)s" \
    "$VIDEO_URL"

# Download subtitles based on source preference
echo "  字幕来源：$SUBTITLE_SOURCE"
if [[ "$SUBTITLE_SOURCE" == "whisper" || "$SUBTITLE_SOURCE" == "whisperx" ]]; then
    if [[ "$SUBTITLE_SOURCE" == "whisper" ]]; then
        echo "  跳过字幕下载，后续将使用 Whisper 本地转录（无高亮，时间轴更干净）"
    else
        echo "  跳过字幕下载，后续将使用 faster-whisper + whisperx 对齐（单词级精度）"
    fi
else
    # Download English subtitles using json3 format (clean, no duplicates)
    # json3 format provides clean text without word-level highlights
    echo "  下载英文字幕（使用 json3 格式，无重复内容）..."
    yt-dlp \
        --cookies-from-browser=chrome \
        --write-auto-subs \
        --sub-lang "en" \
        --sub-format "json3" \
        --skip-download \
        --output "$WORK_DIR/$SAFE_TITLE.%(ext)s" \
        "$VIDEO_URL" || echo "  警告：未找到英文字幕"

    # Convert json3 to SRT
    if [[ -f "$WORK_DIR/$SAFE_TITLE.en.json3" ]]; then
        echo "  转换 json3 为 SRT 格式..."
        python3 << CONVERT_EOF
import json
import re

with open("$WORK_DIR/$SAFE_TITLE.en.json3", 'r', encoding='utf-8') as f:
    data = json.load(f)

def ms_to_srt(ms):
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

events = data.get('events', [])
segments = []

for event in events:
    if 'segs' in event and 'tStartMs' in event:
        text = ''.join(seg.get('utf8', '') for seg in event['segs'])
        text = text.replace('\\n', ' ').strip()
        if text:
            segments.append({
                'start': event['tStartMs'],
                'dur': event.get('dDurationMs', 0),
                'text': text
            })

# Write SRT
with open("$WORK_DIR/$SAFE_TITLE.en.srt", 'w', encoding='utf-8') as f:
    for i, seg in enumerate(segments, 1):
        start = ms_to_srt(seg['start'])
        end = ms_to_srt(seg['start'] + seg['dur'])
        f.write(f"{i}\\n{start} --> {end}\\n{seg['text']}\\n\\n")

print(f"  已转换 {len(segments)} 条字幕")
CONVERT_EOF
        # Clean up json3 file
        rm -f "$WORK_DIR/$SAFE_TITLE.en.json3"
    fi
fi

# Extract audio for voice cloning
echo "  提取音频..."
yt-dlp \
    --cookies-from-browser=chrome \
    -x \
    --audio-format mp3 \
    --output "$WORK_DIR/$SAFE_TITLE.audio.%(ext)s" \
    "$VIDEO_URL"

echo "✅ 下载完成：$WORK_DIR"
