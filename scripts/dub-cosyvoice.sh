#!/bin/bash
# Generate dubbed audio using CosyVoice (local AI TTS by Alibaba)
# Usage: ./dub-cosyvoice.sh <WORK_DIR> <TARGET_LANG> [VOICE_NAME]

set -e

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"

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
echo "  使用语音：CosyVoice 中文女声"

# Generate dubbed audio with CosyVoice
echo "  调用 CosyVoice 生成配音..."
python3 << EOF
import os
import re
import json
import subprocess
import tempfile
from pathlib import Path

# Import cosyvoice
from cosyvoice import CosyVoice

def parse_srt(srt_file):
    """Parse SRT file into segments with timing info"""
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
            time_match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})', time_code)
            if time_match:
                h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, time_match.groups())
                start_ms = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
                end_ms = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2
                segments.append({
                    'index': index,
                    'start_ms': start_ms,
                    'end_ms': end_ms,
                    'start': time_code.split(' --> ')[0],
                    'end': time_code.split(' --> ')[1],
                    'text': text
                })

    return segments

def main():
    # Parse subtitles
    segments = parse_srt("$SRT_FILE")
    print(f"  共 {len(segments)} 条字幕")

    output_files = [None] * len(segments)
    success_count = 0
    failed_count = 0

    # Initialize CosyVoice
    print("  初始化 CosyVoice 模型...")
    model = CosyVoice("CosyVoice-300M-SFT")

    # Process in batches
    batch_size = 10
    for batch_start in range(0, len(segments), batch_size):
        batch_end = min(batch_start + batch_size, len(segments))
        print(f"  处理批次 {batch_start//batch_size + 1}/{(len(segments)-1)//batch_size + 1} (段 {batch_start+1}-{batch_end})...")

        for i in range(batch_start, batch_end):
            seg = segments[i]
            seg_file = f"$BASE_NAME.seg.{i:03d}.mp3"

            try:
                # Clean text
                text = seg['text'].strip()
                text = text.replace('"', "'")

                # Generate audio using inference
                from cosyvoice.utils.file_utils import save_wav_to_mp3
                import numpy as np

                output = model.inference(text)

                # Save audio
                if 'tts_speech' in output:
                    audio_data = output['tts_speech'].numpy()
                    save_wav_to_mp3(audio_data, seg_file)

                    output_files[i] = {
                        'file': seg_file,
                        'start': seg['start'],
                        'end': seg['end'],
                        'start_ms': seg['start_ms'],
                        'end_ms': seg['end_ms']
                    }
                    success_count += 1
                else:
                    print(f"\n  段 {i+1} 无音频输出")
                    failed_count += 1

            except Exception as e:
                print(f"\n  段 {i+1} 生成失败：{e}")
                failed_count += 1
                output_files[i] = {
                    'file': None,
                    'start': seg['start'],
                    'end': seg['end'],
                    'start_ms': seg['start_ms'],
                    'end_ms': seg['end_ms']
                }

    print(f"\n  配音生成完成！成功：{success_count}, 失败：{failed_count}")

    # Create metadata file for merging
    metadata = {
        'segments': output_files,
        'voice': 'CosyVoice-300M-SFT',
        'engine': 'cosyvoice'
    }

    with open("$BASE_NAME.voice-map.json", 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"  已保存元数据：$BASE_NAME.voice-map.json")

if __name__ == "__main__":
    main()
EOF

echo "✅ 配音生成完成"
