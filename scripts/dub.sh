#!/bin/bash
# Generate dubbed audio using ElevenLabs
# Usage: ./dub.sh <WORK_DIR> <TARGET_LANG> [VOICE_LIBRARY]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

# Load environment variables from .env file if exists
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
VOICE_LIBRARY="${3:-false}"

cd "$WORK_DIR"

# Find files - for TTS generation, use English subtitle (for voice cloning accuracy)
# First try to find English-only subtitle file (created when bilingual mode is enabled)
# Use find instead of ls to handle filenames with spaces
EN_SRT_FILE=$(find . -maxdepth 1 -name "*.en.only.srt" -type f | head -1)

# If no English-only file, use original English subtitle
if [[ -z "$EN_SRT_FILE" ]]; then
    EN_SRT_FILE=$(find . -maxdepth 1 -name "*.en.srt" -type f | head -1)
fi

# For dubbed audio output naming, still use TARGET_LANG subtitle
# Use find instead of ls to handle filenames with spaces
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

# Use English subtitle for TTS generation if available, fallback to target language subtitle
if [[ -n "$EN_SRT_FILE" ]] && [[ -f "$EN_SRT_FILE" ]]; then
    SRT_FILE="$EN_SRT_FILE"
    echo "  使用英文字幕生成 TTS：$SRT_FILE"
else
    SRT_FILE="$TARGET_SRT_FILE"
    echo "  使用中文字幕生成 TTS：$SRT_FILE"
fi

BASE_NAME="${TARGET_SRT_FILE%.*}"
BASE_NAME="${BASE_NAME%.$TARGET_LANG}"

echo "  字幕文件：$SRT_FILE"
echo "  参考音频：$AUDIO_FILE"

# Generate dubbed audio with ElevenLabs
echo "  调用 ElevenLabs 生成配音..."
python3 << EOF
import os
import re
import time
import requests
import json

# Setup API
api_key = os.environ.get('ELEVENLABS_API_KEY')
if not api_key:
    print("  ❌ 未设置 ELEVENLABS_API_KEY")
    exit(1)

# Default voice ID (Adam - multilingual)
DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"

# Rate limiting: wait between requests (seconds)
REQUEST_DELAY = 1.0  # Base delay between successful requests
MAX_RETRIES = 5      # Max retries per segment
RETRY_DELAY = 3.0    # Delay before first retry

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
                    'text': text
                })
    
    return segments

def time_to_ms(time_str):
    """Convert SRT time to milliseconds"""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600000 + m * 60000 + s * 1000 + ms
    return 0

def get_voice_id_from_audio(audio_file):
    """Clone voice from reference audio using ElevenLabs v2 API"""
    try:
        print(f"    正在克隆声音...")

        # Use requests to call ElevenLabs voice cloning API directly
        import requests

        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "multipart/form-data"
        }

        files = {
            'files': ('audio.mp3', open(audio_file, 'rb'), 'audio/mpeg')
        }

        data = {
            'name': 'Cloned Voice',
            'description': 'Voice cloned from video'
        }

        response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        result = response.json()

        voice_id = result.get('voice_id')
        if voice_id:
            print(f"    声音克隆成功：{voice_id}")
            return voice_id
        else:
            print(f"    声音克隆失败：{result}")
            return None
    except Exception as e:
        print(f"    声音克隆失败：{e}")
        print(f"    使用默认声音")
        return None  # Will use default voice

# Parse subtitles
segments = parse_srt("$SRT_FILE")
print(f"  共 {len(segments)} 条字幕")

# Get voice ID
voice_id = None
if "$VOICE_LIBRARY" != "true":
    voice_id = get_voice_id_from_audio("$AUDIO_FILE")

if not voice_id:
    voice_id = DEFAULT_VOICE_ID  # Default voice
    print(f"  使用默认声音：{voice_id}")

# Generate audio for each segment with retry logic
output_files = []
failed_count = 0
success_count = 0

for i, seg in enumerate(segments):
    print(f"    生成 {i+1}/{len(segments)}...", end='\r')

    success = False
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # Generate speech using requests directly
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": api_key,
                "Content-Type": "application/json"
            }

            payload = {
                "text": seg['text'],
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True
                }
            }

            response = requests.post(url, headers=headers, json=payload, timeout=120)

            # Handle rate limit and unusual activity
            if response.status_code == 429 or (response.status_code == 401 and 'unusual_activity' in response.text.lower()):
                wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                print(f"\n    段 {i+1} 触发限流，等待 {wait_time:.1f}秒...")
                time.sleep(wait_time)
                continue

            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code} - {response.text[:200]}")

            # Save segment
            seg_file = f"$BASE_NAME.seg.{i:03d}.mp3"
            with open(seg_file, 'wb') as f:
                f.write(response.content)

            output_files.append({
                'file': seg_file,
                'start': seg['start'],
                'end': seg['end']
            })

            success = True
            success_count += 1
            # Rate limiting
            time.sleep(REQUEST_DELAY)
            break

        except Exception as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(f"\n    段 {i+1} 尝试 {attempt+1} 失败：{e}, 等待 {wait_time:.1f}秒后重试...")
                time.sleep(wait_time)
            else:
                print(f"\n    段 {i+1} 生成失败：{last_error}")
                failed_count += 1
                # Create silent segment as placeholder
                output_files.append({
                    'file': None,
                    'start': seg['start'],
                    'end': seg['end']
                })

print(f"  配音生成完成！成功：{success_count}, 失败：{failed_count}")

# Create metadata file for merging
metadata = {
    'segments': output_files,
    'voice_id': voice_id
}

with open("$BASE_NAME.voice-map.json", 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"  已保存元数据：$BASE_NAME.voice-map.json")
EOF

echo "✅ 配音生成完成"
