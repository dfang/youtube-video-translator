#!/bin/bash
# Generate dubbed audio using ElevenLabs (simplified version)
# Usage: ./dub.sh <WORK_DIR> <TARGET_LANG> [VOICE_LIBRARY]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

# Load environment variables
if [[ -f "$ENV_FILE" ]]; then
    source "$ENV_FILE"
fi

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
VOICE_LIBRARY="${3:-false}"

cd "$WORK_DIR"

# Find files
SRT_FILE=$(ls *.$TARGET_LANG.srt 2>/dev/null | head -1)
AUDIO_FILE=$(ls *.audio.mp3 2>/dev/null | head -1)

if [[ -z "$SRT_FILE" ]]; then
    echo "❌ 未找到中文字幕文件"
    exit 1
fi

if [[ -z "$AUDIO_FILE" ]]; then
    echo "❌ 未找到音频文件"
    exit 1
fi

BASE_NAME="${SRT_FILE%.*}"
BASE_NAME="${BASE_NAME%.$TARGET_LANG}"

echo "  字幕文件：$SRT_FILE"
echo "  参考音频：$AUDIO_FILE"
echo "  调用 ElevenLabs 生成配音..."

# Generate audio using simple Python script
python3 << PYEOF
import os
import re
import time
import requests

api_key = os.environ.get('ELEVENLABS_API_KEY', '')
if not api_key:
    print("  ❌ 未设置 ELEVENLABS_API_KEY")
    exit(1)

def parse_srt(srt_file):
    segments = []
    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    blocks = re.split(r'\n\n+', content.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_code = lines[1]
            text = '\n'.join(lines[2:])
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_code)
            if time_match:
                segments.append({
                    'start': time_match.group(1),
                    'end': time_match.group(2),
                    'text': text
                })
    return segments

segments = parse_srt("$SRT_FILE")
print(f"  共 {len(segments)} 条字幕")

# Use default multilingual voice
voice_id = "pNInz6obpgDQGcFmaJgB"  # Adam

output_files = []
for i, seg in enumerate(segments[:50]):  # Limit to first 50 for testing
    text = seg['text'].strip()
    if len(text) < 2:
        continue
    
    print(f"    生成 {i+1}/{min(50, len(segments))}...", end='\r')
    
    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }
        )
        
        if response.status_code == 200:
            seg_file = f"$BASE_NAME.seg.{i:03d}.mp3"
            with open(seg_file, 'wb') as f:
                f.write(response.content)
            output_files.append(seg_file)
            time.sleep(0.3)  # Rate limit
        else:
            print(f"\n    API 错误：{response.status_code} - {response.text[:100]}")
            
    except Exception as e:
        print(f"\n    错误：{e}")

print(f"\n  生成完成：{len(output_files)} 个音频片段")

# Create metadata
import json
metadata = {'segments': output_files, 'voice_id': voice_id}
with open("$BASE_NAME.voice-map.json", 'w') as f:
    json.dump(metadata, f, indent=2)
PYEOF

echo "✅ 配音生成完成"
