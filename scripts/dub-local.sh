#!/bin/bash
# Generate dubbed audio using edge-tts (local/free Microsoft TTS)
# Usage: ./dub-local.sh <WORK_DIR> <TARGET_LANG> [VOICE_NAME]

set -e

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
VOICE_NAME="${3:-zh-CN-YunxiNeural}"  # Default male voice, warm and lively

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
echo "  使用语音：$VOICE_NAME"

# Generate dubbed audio with edge-tts
echo "  调用 edge-tts 生成配音..."
python3 << EOF
import os
import re
import asyncio
import edge_tts
import json
from pathlib import Path

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

async def generate_audio(text, output_file, voice="$VOICE_NAME", timeout=30, max_retries=3):
    """Generate audio using edge-tts with retry logic"""
    for attempt in range(max_retries):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(communicate.save(output_file), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                raise Exception("Timeout after {} retries".format(max_retries))
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                raise e
    return False

async def main():
    # Parse subtitles
    segments = parse_srt("$SRT_FILE")
    print(f"  共 {len(segments)} 条字幕")

    output_files = [None] * len(segments)
    success_count = 0
    failed_count = 0

    # Use semaphore to limit concurrent tasks
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent generations

    async def generate_segment(i, seg):
        async with semaphore:
            seg_file = f"$BASE_NAME.seg.{i:03d}.mp3"
            try:
                # Clean text
                text = seg['text'].strip()
                text = text.replace('"', "'")

                await generate_audio(text, seg_file, timeout=20, max_retries=2)
                return i, {
                    'file': seg_file,
                    'start': seg['start'],
                    'end': seg['end'],
                    'start_ms': seg['start_ms'],
                    'end_ms': seg['end_ms']
                }, True
            except Exception as e:
                print(f"\n  段 {i+1} 生成失败：{e}")
                return i, {
                    'file': None,
                    'start': seg['start'],
                    'end': seg['end'],
                    'start_ms': seg['start_ms'],
                    'end_ms': seg['end_ms']
                }, False

    # Process in batches with progress
    batch_size = 50
    for batch_start in range(0, len(segments), batch_size):
        batch_end = min(batch_start + batch_size, len(segments))
        print(f"  处理批次 {batch_start//batch_size + 1}/{(len(segments)-1)//batch_size + 1} (段 {batch_start+1}-{batch_end})...")

        tasks = [generate_segment(i, seg) for i, seg in enumerate(segments[batch_start:batch_end], start=batch_start)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                print(f"\n  批次错误：{result}")
                failed_count += 1
            else:
                i, data, success = result
                output_files[i] = data
                if success:
                    success_count += 1
                else:
                    failed_count += 1

    # Filter out None values and sort
    final_output = [x for x in output_files if x is not None]
    final_output.sort(key=lambda x: x['start_ms'])

    print(f"\n  配音生成完成！成功：{success_count}, 失败：{failed_count}")

    # Create metadata file for merging
    metadata = {
        'segments': output_files,
        'voice': "$VOICE_NAME",
        'engine': 'edge-tts'
    }

    with open("$BASE_NAME.voice-map.json", 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"  已保存元数据：$BASE_NAME.voice-map.json")

# Run async
asyncio.run(main())
EOF

echo "✅ 配音生成完成"
