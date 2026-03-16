#!/bin/bash
# Transcribe using faster-whisper + whisperx alignment
# Usage: ./whisperx-transcribe.sh <WORK_DIR> <LANGUAGE>
#LANGUAGE: en (default), zh, ja, ko, etc.

set -e

WORK_DIR="$1"
LANGUAGE="${2:-en}"

cd "$WORK_DIR"

echo "🎯 使用 faster-whisper + whisperx 进行转录和对齐"

# Find video file
VIDEO_FILE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
if [[ -z "$VIDEO_FILE" ]]; then
    echo "❌ 未找到视频文件"
    exit 1
fi

VIDEO_BASE="${VIDEO_FILE%.original.mp4}"
AUDIO_FILE="$VIDEO_BASE.audio.wav"

# Step 1: Extract audio for whisperx
echo "  [1/4] 提取音频用于 whisperx 对齐..."
if [[ ! -f "$AUDIO_FILE" ]]; then
    ffmpeg -i "$VIDEO_FILE" -vn -acodec pcm_s16le -ar 16000 -ac 1 "$AUDIO_FILE" -y 2>/dev/null
    echo "  已提取音频：$AUDIO_FILE"
else
    echo "  音频文件已存在，跳过提取"
fi

# Step 2: Transcribe with faster-whisper
echo "  [2/4] 使用 faster-whisper 进行转录..."
TRANSCRIPT_SRT="$VIDEO_BASE.transcript.srt"

if command -v faster-whisper &> /dev/null; then
    faster-whisper "$VIDEO_FILE" \
        --model large-v3 \
        --output_dir "$WORK_DIR" \
        --output_format srt \
        --language "$LANGUAGE" \
        --compute_type float16 \
        2>/dev/null

    # Rename output - faster-whisper may output to different locations
    if [[ -f "${VIDEO_FILE}.srt" ]]; then
        mv "${VIDEO_FILE}.srt" "$TRANSCRIPT_SRT"
    elif [[ -f "${VIDEO_BASE}.original.srt" ]]; then
        mv "${VIDEO_BASE}.original.srt" "$TRANSCRIPT_SRT"
    elif [[ -f "${VIDEO_BASE}.srt" ]]; then
        mv "${VIDEO_BASE}.srt" "$TRANSCRIPT_SRT"
    elif [[ -f "video.srt" ]]; then
        mv "video.srt" "$TRANSCRIPT_SRT"
    fi

    if [[ -f "$TRANSCRIPT_SRT" ]]; then
        echo "  转录完成：$TRANSCRIPT_SRT"
    else
        echo "  ⚠️ faster-whisper 输出文件未找到，尝试使用 whisperx 直接转录"
    fi
else
    echo "  ⚠️ faster-whisper 未安装，使用 whisperx 直接转录"
fi

# Step 3: Align with whisperx
echo "  [3/4] 使用 whisperx 进行单词级对齐..."
ALIGNED_SRT="$VIDEO_BASE.aligned.srt"

if command -v whisperx &> /dev/null; then
    # Run whisperx align
    # whisperx outputs multiple files, we want the final aligned SRT
    whisperx align \
        --output_format srt \
        --model large-v3 \
        --language "$LANGUAGE" \
        --compute_type float16 \
        "$AUDIO_FILE" \
        "$TRANSCRIPT_SRT" \
        --output_dir "$WORK_DIR" \
        2>/dev/null

    # Find and rename aligned output
    # whisperx typically outputs to {input}.aligned.srt or similar
    if [[ -f "${TRANSCRIPT_SRT%.srt}.aligned.srt" ]]; then
        mv "${TRANSCRIPT_SRT%.srt}.aligned.srt" "$ALIGNED_SRT"
    elif [[ -f "${VIDEO_BASE}.original.aligned.srt" ]]; then
        mv "${VIDEO_BASE}.original.aligned.srt" "$ALIGNED_SRT"
    elif [[ -f "video.aligned.srt" ]]; then
        mv "video.aligned.srt" "$ALIGNED_SRT"
    fi

    if [[ -f "$ALIGNED_SRT" ]]; then
        echo "  对齐完成：$ALIGNED_SRT"
        # Use aligned subtitle as final output
        FINAL_SRT="$ALIGNED_SRT"
    else
        echo "  ⚠️ whisperx 对齐输出未找到，使用原始转录"
        FINAL_SRT="$TRANSCRIPT_SRT"
    fi

    # Clean up intermediate files
    rm -f "$TRANSCRIPT_SRT"
else
    echo "  ⚠️ whisperx 未安装，跳过对齐步骤"
    FINAL_SRT="$TRANSCRIPT_SRT"
fi

# Step 4: Rename to final English subtitle
echo "  [4/4] 保存最终英文字幕..."
FINAL_EN_SRT="$VIDEO_BASE.en.srt"

if [[ -f "$FINAL_SRT" ]]; then
    # Clean up any duplicate content in whisperx output
    python3 << 'CLEAN_EOF'
import re

def clean_whisperx_srt(input_file, output_file):
    """Clean whisperx SRT output - remove duplicate lines and fix formatting"""
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\n+', content.strip())
    cleaned_blocks = []
    prev_text = ""

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue

        try:
            index = lines[0]
            time_code = lines[1]
            text = ' '.join(lines[2:]).strip()
        except:
            continue

        # Skip if text is too similar to previous (whisperx sometimes outputs overlapping segments)
        if prev_text and (text in prev_text or prev_text in text):
            if len(text) < len(prev_text):
                continue

        # Validate time code
        if not re.match(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}', time_code):
            continue

        cleaned_blocks.append({
            'index': len(cleaned_blocks) + 1,
            'time': time_code,
            'text': text
        })
        prev_text = text

    # Write cleaned SRT
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, block in enumerate(cleaned_blocks, 1):
            f.write(f"{i}\n")
            f.write(f"{block['time']}\n")
            f.write(f"{block['text']}\n\n")

    print(f"  已清理 WhisperX 输出：{len(cleaned_blocks)} 条字幕")

clean_whisperx_srt("$FINAL_SRT", "$FINAL_EN_SRT")
CLEAN_EOF

    echo "  已保存英文字幕：$FINAL_EN_SRT"
else
    echo "  ❌ 转录失败，未生成字幕文件"
    exit 1
fi

# Clean up intermediate files
rm -f "$FINAL_SRT"
rm -f "$AUDIO_FILE"

echo "✅ WhisperX 转录完成（单词级对齐，时间轴精确）"
