#!/bin/bash
# Generate dubbed audio using edge-tts or piper-tts
# Usage: ./dub.sh <WORK_DIR> <TARGET_LANG> [VOICE_NAME] [TTS_ENGINE]
# VOICE_NAME: Optional, default is zh-CN-XiaoxiaoNeural for Chinese
# TTS_ENGINE: Optional, default is edge-tts, option: piper-tts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
VOICE_NAME="${3:-}"
TTS_ENGINE="${4:-edge-tts}"  # default: edge-tts, option: piper-tts

cd "$WORK_DIR"

# Create audio subdirectory for generated segments
AUDIO_OUTPUT_DIR="$WORK_DIR/audio"
mkdir -p "$AUDIO_OUTPUT_DIR"

# Find subtitle files for TTS generation
# Priority 1: Target language subtitle (for dubbed audio, use translated subtitles)
SRT_FILE=$(find . -maxdepth 1 -name "*.$TARGET_LANG.srt" -type f | head -1)

# Priority 2: English-only subtitle file (for bilingual mode TTS generation fallback)
if [[ -z "$SRT_FILE" ]]; then
    SRT_FILE=$(find . -maxdepth 1 -name "*.en.only.srt" -type f | head -1)
fi

# Priority 3: Original English subtitle (last resort)
if [[ -z "$SRT_FILE" ]]; then
    SRT_FILE=$(find . -maxdepth 1 -name "*.en.srt" -type f | head -1)
fi

AUDIO_FILE=$(find . -maxdepth 1 -name "*.audio.mp3" -type f | head -1)

if [[ -z "$SRT_FILE" ]]; then
    echo "❌ 未找到字幕文件"
    exit 1
fi

if [[ -z "$AUDIO_FILE" ]]; then
    echo "❌ 未找到音频文件"
    exit 1
fi

echo "  使用字幕文件：$SRT_FILE"
echo "  参考音频：$AUDIO_FILE"

BASE_NAME="${SRT_FILE%.*}"
# Remove language suffix to get base name
BASE_NAME="${BASE_NAME%.en.only}"
BASE_NAME="${BASE_NAME%.en}"
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
echo "  TTS 引擎：$TTS_ENGINE"

# Check piper-tts installation if selected
if [[ "$TTS_ENGINE" = "piper-tts" ]]; then
    if ! command -v piper &> /dev/null; then
        echo "❌ 未找到 piper 命令"
        echo "💡 请安装 piper-tts:"
        echo "   brew install piper-tts  # macOS"
        echo "   或参考：https://github.com/rhasspy/piper"
        exit 1
    fi

    # Auto-download Chinese voice model if not exists
    PIPER_VOICES_DIR="${PIPER_VOICES_DIR:-$HOME/.local/share/piper}"
    PIPER_MODEL="$PIPER_VOICES_DIR/zh_CN/zh_CN-huashuo-j.onnx"
    PIPER_CONFIG="$PIPER_VOICES_DIR/zh_CN/zh_CN-huashuo-j.onnx.json"

    if [[ ! -f "$PIPER_MODEL" ]]; then
        echo "🔄 下载 Piper 中文语音模型..."
        mkdir -p "$PIPER_VOICES_DIR/zh_CN"
        curl -sL "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huashuo/joke/zh_CN-huashuo-j.onnx" -o "$PIPER_MODEL"
        curl -sL "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huashuo/joke/zh_CN-huashuo-j.onnx.json" -o "$PIPER_CONFIG"
        echo "✅ 模型下载完成：$PIPER_MODEL"
    fi
fi

# Generate dubbed audio
echo "  开始生成配音 ($TTS_ENGINE)..."
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

def generate_tts_edge_tts(text, output_file, voice_name):
    """Generate TTS using edge-tts"""
    try:
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

def generate_tts_piper(text, output_file, model_path, config_path):
    """Generate TTS using piper-tts"""
    try:
        # Use piper command line
        result = subprocess.run([
            'piper',
            '-m', model_path,
            '-f', output_file,
            '--sentence_silence', '0.2'
        ], input=text.encode('utf-8'), capture_output=True, timeout=60)

        if result.returncode != 0:
            print(f"\n    生成失败：{result.stderr[:200]}", flush=True)
            return False

        return os.path.exists(output_file) and os.path.getsize(output_file) > 0
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

TTS_ENGINE = "$TTS_ENGINE"
PIPER_MODEL = "$PIPER_MODEL" if TTS_ENGINE == "piper-tts" else ""
PIPER_CONFIG = "$PIPER_CONFIG" if TTS_ENGINE == "piper-tts" else ""

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

    # Generate TTS based on engine
    if TTS_ENGINE == "piper-tts":
        if generate_tts_piper(text, seg_file, PIPER_MODEL, PIPER_CONFIG):
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
    else:
        # edge-tts
        if generate_tts_edge_tts(text, seg_file, "$VOICE_NAME"):
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

print(f"\n  配音生成完成！成功：{success_count}, 失败：{failed_count}", flush=True)

# Create metadata file for merging
metadata = {
    'segments': output_files,
    'voice': "$VOICE_NAME" if TTS_ENGINE == "edge-tts" else "piper-zh_CN-huashuo",
    'engine': TTS_ENGINE
}

with open("$BASE_NAME.voice-map.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"  已保存元数据：$BASE_NAME.voice-map.json", flush=True)
EOF

echo "✅ 配音生成完成"
