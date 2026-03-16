#!/bin/bash
# Generate dubbed audio using edge-tts
# Usage: ./dub.sh <WORK_DIR> <TARGET_LANG> [VOICE_NAME]
# VOICE_NAME: Optional, default is zh-CN-XiaoxiaoNeural for Chinese

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
VOICE_NAME="${3:-}"

cd "$WORK_DIR"

# Create audio subdirectory for generated segments
AUDIO_OUTPUT_DIR="$WORK_DIR/audio"
mkdir -p "$AUDIO_OUTPUT_DIR"

# Find subtitle files
# First try to find English-only subtitle file (for bilingual mode)
EN_SRT_FILE=$(find . -maxdepth 1 -name "*.en.only.srt" -type f | head -1)

# If no English-only file, use original English subtitle
if [[ -z "$EN_SRT_FILE" ]]; then
    EN_SRT_FILE=$(find . -maxdepth 1 -name "*.en.srt" -type f | head -1)
fi

# Target language subtitle for output naming
TARGET_SRT_FILE=$(find . -maxdepth 1 -name "*.$TARGET_LANG.srt" -type f | head -1)
AUDIO_FILE=$(find . -maxdepth 1 -name "*.audio.mp3" -type f | head -1)

if [[ -z "$TARGET_SRT_FILE" ]]; then
    echo "❌ 未找到中文字幕文件"
    exit 1
fi

if [[ -z "$AUDIO_FILE" ]]; then
    echo "❌ 未找到音频文件"
    exit 1
fi

# Use Chinese subtitle for TTS generation (edge-tts supports Chinese natively)
SRT_FILE="$TARGET_SRT_FILE"
echo "  使用字幕文件：$SRT_FILE"
echo "  参考音频：$AUDIO_FILE"

BASE_NAME="${TARGET_SRT_FILE%.*}"
BASE_NAME="${BASE_NAME%.$TARGET_LANG}"

# Determine voice based on target language
if [[ -z "$VOICE_NAME" ]]; then
    case "$TARGET_LANG" in
        zh-CN|zh)
            VOICE_NAME="zh-CN-XiaoxiaoNeural"
            ;;
        zh-HK|zh-Hant)
            VOICE_NAME="zh-HK-HiuMaanNeural"
            ;;
        zh-TW)
            VOICE_NAME="zh-TW-HsiaoChenNeural"
            ;;
        ja)
            VOICE_NAME="ja-JP-NanamiNeural"
            ;;
        ko)
            VOICE_NAME="ko-KR-SunHiNeural"
            ;;
        en)
            VOICE_NAME="en-US-JennyNeural"
            ;;
        es)
            VOICE_NAME="es-ES-ElviraNeural"
            ;;
        fr)
            VOICE_NAME="fr-FR-DeniseNeural"
            ;;
        de)
            VOICE_NAME="de-DE-KatjaNeural"
            ;;
        *)
            VOICE_NAME="zh-CN-XiaoxiaoNeural"
            ;;
    esac
fi

echo "  使用语音：$VOICE_NAME"

# Generate dubbed audio with edge-tts
echo "  调用 edge-tts 生成配音..."
python3 << EOF
import os
import re
import subprocess
import json
import sys

def parse_srt(srt_file):
    """Parse SRT file into segments"""
    segments = []

    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\n+', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            index = lines[0]
            time_code = lines[1]
            text = '\n'.join(lines[2:])

            # Parse time codes
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_code)
            if time_match:
                start = time_match.group(1)
                end = time_match.group(2)
                segments.append({
                    'index': index,
                    'start': start,
                    'end': end,
                    'text': text.strip()
                })

    return segments

def time_to_ms(time_str):
    """Convert SRT time to milliseconds"""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600000 + m * 60000 + s * 1000 + ms
    return 0

def ms_to_time(ms):
    """Convert milliseconds to SRT time format"""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def generate_tts(text, output_file, voice_name):
    """Generate TTS using edge-tts"""
    try:
        # Use edge-tts command line
        result = subprocess.run([
            'edge-tts',
            '--voice', voice_name,
            '--text', text,
            '--write-media', output_file
        ], capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            print(f"\n    生成失败：{result.stderr[:200]}", flush=True)
            return False

        return os.path.exists(output_file)
    except subprocess.TimeoutExpired:
        print(f"\n    生成超时", flush=True)
        return False
    except Exception as e:
        print(f"\n    生成失败：{e}", flush=True)
        return False

# Parse subtitles
segments = parse_srt("$SRT_FILE")
print(f"  共 {len(segments)} 条字幕", flush=True)

# Generate audio for each segment
output_files = []
failed_count = 0
success_count = 0

print(f"  开始生成 {len(segments)} 条字幕配音...", flush=True)

start_time = __import__('time').time()

for i, seg in enumerate(segments):
    seg_file = f"$AUDIO_OUTPUT_DIR/$BASE_NAME.seg.{i:03d}.mp3"
    # Progress with percentage and ETA
    elapsed = __import__('time').time() - start_time
    avg_time = elapsed / (i + 1) if i > 0 else 0
    remaining = (len(segments) - i - 1) * avg_time
    progress = (i + 1) / len(segments) * 100
    print(f"\r    生成 {i+1}/{len(segments)} ({progress:.1f}%) - 剩余 {remaining:.0f}s   ", end='', flush=True)

    text = seg['text']
    # Clean text - remove very short texts or special characters
    if len(text.strip()) < 1:
        # Create silent segment
        output_files.append({
            'file': None,
            'start': seg['start'],
            'end': seg['end']
        })
        failed_count += 1
        continue

    # Generate TTS
    if generate_tts(text, seg_file, "$VOICE_NAME"):
        output_files.append({
            'file': seg_file,
            'start': seg['start'],
            'end': seg['end']
        })
        success_count += 1
    else:
        output_files.append({
            'file': None,
            'start': seg['start'],
            'end': seg['end']
        })
        failed_count += 1

print(f"  配音生成完成！成功：{success_count}, 失败：{failed_count}", flush=True)

# Create metadata file for merging
metadata = {
    'segments': output_files,
    'voice': "$VOICE_NAME"
}

with open("$BASE_NAME.voice-map.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"  已保存元数据：$BASE_NAME.voice-map.json", flush=True)
EOF

echo "✅ 配音生成完成"
