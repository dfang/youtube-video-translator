#!/bin/bash
# Generate dubbed audio using Piper TTS (local, fast, offline)
# Usage: ./dub-piper.sh <WORK_DIR> <TARGET_LANG> [VOICE_NAME]

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

# Download Chinese voice model if not exists
VOICE_MODEL="${BASE_NAME}.onnx"
VOICE_CONFIG="${BASE_NAME}.onnx.json"

if [[ ! -f "$VOICE_MODEL" ]]; then
    echo "  下载中文语音模型..."
    # Using Chinese female voice: zh-CN-Xiaoxiao
    curl -sL "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/Xiaoxiao/high/zh-CN-Xiaoxiao-high.onnx" -o "$VOICE_MODEL"
    curl -sL "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/Xiaoxiao/high/zh-CN-Xiaoxiao-high.onnx.json" -o "$VOICE_CONFIG"
    echo "  语音模型下载完成"
fi

# Generate dubbed audio with Piper
echo "  调用 Piper TTS 生成配音..."
python3 << EOF
import os
import re
import json
import wave
import numpy as np
from pathlib import Path
from piper import PiperVoice

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

def save_wav_to_mp3(audio_data, sample_rate, output_file):
    """Convert wav data to MP3 using ffmpeg"""
    import subprocess
    import tempfile

    # Write wav to temp file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        with wave.open(tmp.name, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data)
        tmp_wav = tmp.name

    # Convert to mp3
    subprocess.run([
        'ffmpeg', '-y', '-i', tmp_wav,
        '-b:a', '128k', output_file
    ], check=True, capture_output=True)

    # Cleanup
    os.remove(tmp_wav)

def main():
    # Parse subtitles
    segments = parse_srt("$SRT_FILE")
    print(f"  共 {len(segments)} 条字幕")

    output_files = [None] * len(segments)
    success_count = 0
    failed_count = 0

    # Load Piper voice
    print("  加载 Piper 语音模型...")
    voice = PiperVoice.load("$VOICE_MODEL", config_path="$VOICE_CONFIG")

    # Process segments
    batch_size = 20
    for batch_start in range(0, len(segments), batch_size):
        batch_end = min(batch_start + batch_size, len(segments))
        print(f"  处理批次 {batch_start//batch_size + 1}/{(len(segments)-1)//batch_size + 1} (段 {batch_start+1}-{batch_end})...")

        for i in range(batch_start, batch_end):
            seg = segments[i]
            seg_file = f"$BASE_NAME.seg.{i:03d}.mp3"

            try:
                # Clean text
                text = seg['text'].strip()

                # Synthesize speech
                audio_data = voice.synthesize(text)

                # Get sample rate from voice config
                sample_rate = voice.config.sample_rate

                # Save to mp3
                save_wav_to_mp3(audio_data, sample_rate, seg_file)

                output_files[i] = {
                    'file': seg_file,
                    'start': seg['start'],
                    'end': seg['end'],
                    'start_ms': seg['start_ms'],
                    'end_ms': seg['end_ms']
                }
                success_count += 1

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
        'voice': 'zh-CN-Xiaoxiao-high',
        'engine': 'piper-tts'
    }

    with open("$BASE_NAME.voice-map.json", 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"  已保存元数据：$BASE_NAME.voice-map.json")

if __name__ == "__main__":
    main()
EOF

echo "✅ 配音生成完成"
