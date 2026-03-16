#!/bin/bash
# Transcribe using faster-whisper + whisperx alignment (optional)
# Usage: ./whisperx-transcribe.sh <WORK_DIR> <LANGUAGE>
# LANGUAGE: en (default), zh, ja, ko, etc.

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

# Step 1: Extract audio for whisperx (optional)
echo "  [1/3] 提取音频用于 whisperx 对齐..."
if [[ ! -f "$AUDIO_FILE" ]]; then
    ffmpeg -i "$VIDEO_FILE" -vn -acodec pcm_s16le -ar 16000 -ac 1 "$AUDIO_FILE" -y 2>/dev/null
    echo "  已提取音频：$AUDIO_FILE"
else
    echo "  音频文件已存在，跳过提取"
fi

# Step 2: Transcribe with faster-whisper (or openai-whisper as fallback)
echo "  [2/3] 使用 faster-whisper 进行转录..."
TRANSCRIPT_SRT="$VIDEO_BASE.transcript.srt"

# Try faster-whisper first, fall back to openai-whisper
python3 << TRANScribe_EOF
import os
import sys

video_file = "$VIDEO_FILE"
output_file = "$TRANSCRIPT_SRT"
language = "$LANGUAGE"

# Try faster-whisper first
try:
    from faster_whisper import WhisperModel
    print("  加载 faster-whisper 模型 (medium)...")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    print("  开始转录...")
    segments, info = model.transcribe(video_file, language=language, vad_filter=True)
    segments = list(segments)
except Exception as e:
    print(f"  faster-whisper 失败：{e}")
    print("  使用 openai-whisper (base)...")
    import whisper
    model = whisper.load_model("base")
    print("  开始转录...")
    result = model.transcribe(video_file, language=language)
    segments = result['segments']

# Write SRT output
with open(output_file, 'w', encoding='utf-8') as f:
    for i, segment in enumerate(segments, 1):
        start = segment.start if hasattr(segment, 'start') else segment['start']
        end = segment.end if hasattr(segment, 'end') else segment['end']
        text = segment.text.strip() if hasattr(segment, 'text') else segment['text'].strip()

        def format_time(t):
            hours = int(t // 3600)
            minutes = int((t % 3600) // 60)
            seconds = int(t % 60)
            millis = int((t % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

        f.write(f"{i}\n")
        f.write(f"{format_time(start)} --> {format_time(end)}\n")
        f.write(f"{text}\n\n")

print(f"  转录完成：{len(segments)} 条字幕")
TRANScribe_EOF

if [[ -f "$TRANSCRIPT_SRT" ]]; then
    echo "  转录完成：$TRANSCRIPT_SRT"
else
    echo "  ❌ faster-whisper 转录失败"
    exit 1
fi

# Step 3: Try whisperx alignment (optional, skip if network fails)
echo "  [3/3] 尝试使用 whisperx 进行单词级对齐..."
ALIGNED_SRT="$VIDEO_BASE.aligned.srt"
ALIGNMENT_SUCCESS=false

# Try whisperx alignment with timeout and error handling
python3 << ALIGN_EOF 2>/dev/null && ALIGNMENT_SUCCESS=true || echo "  ⚠️ whisperx 对齐跳过（网络问题或模型不可用），使用 faster-whisper 原始转录"
import os
import sys
import whisperx
import torch

audio_file = "$AUDIO_FILE"
transcript_file = "$TRANSCRIPT_SRT"
output_file = "$ALIGNED_SRT"
language = "$LANGUAGE"

print("  加载 whisperx 模型...")
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"  使用设备：{device}")

# Load alignment model with timeout
try:
    align_model, align_metadata = whisperx.load_align_model(
        language_code=language,
        device=device
    )
except Exception as e:
    print(f"  加载对齐模型失败：{e}")
    sys.exit(1)

# Load audio
audio = whisperx.load_audio(audio_file)

# Load transcript and convert to whisperx format
import re

segments = []
with open(transcript_file, 'r', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'\n\n+', content.strip())
for block in blocks:
    lines = block.strip().split('\n')
    if len(lines) >= 3:
        time_code = lines[1]
        text = ' '.join(lines[2:])

        # Parse time codes (SRT format: HH:MM:SS,mmm)
        def parse_time(t):
            h, m, rest = t.split(':')
            s, ms = rest.replace(',', '.').split('.')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

        start, end = time_code.split(' --> ')
        start = parse_time(start.strip())
        end = parse_time(end.strip())

        segments.append({
            'start': start,
            'end': end,
            'text': text.strip()
        })

print(f"  加载了 {len(segments)} 条字幕进行对齐...")

# Align
result = whisperx.align(
    segments,
    align_model,
    align_metadata,
    audio,
    device,
    return_char_alignments=False
)

# Write aligned SRT
def format_time(t):
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    millis = int((t % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

with open(output_file, 'w', encoding='utf-8') as f:
    for i, segment in enumerate(result['segments'], 1):
        f.write(f"{i}\n")
        f.write(f"{format_time(segment['start'])} --> {format_time(segment['end'])}\n")
        f.write(f"{segment['text'].strip()}\n\n")

print(f"  对齐完成：{len(result['segments'])} 条字幕")
ALIGN_EOF

# Determine final output
if [[ "$ALIGNMENT_SUCCESS" == "true" && -f "$ALIGNED_SRT" ]]; then
    echo "  ✅ whisperx 对齐完成：$ALIGNED_SRT"
    FINAL_SRT="$ALIGNED_SRT"
else
    echo "  使用 faster-whisper 原始转录：$TRANSCRIPT_SRT"
    FINAL_SRT="$TRANSCRIPT_SRT"
fi

# Step 4: Rename to final English subtitle and clean up
echo "  保存最终英文字幕..."
FINAL_EN_SRT="$VIDEO_BASE.en.srt"

# Clean up SRT output
python3 -c "
import re
import sys

final_srt = '$FINAL_SRT'
final_en_srt = '$FINAL_EN_SRT'

def clean_whisperx_srt(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\n+', content.strip())
    cleaned_blocks = []
    prev_text = ''

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        try:
            time_code = lines[1]
            text = ' '.join(lines[2:]).strip()
        except:
            continue
        if prev_text and (text in prev_text or prev_text in text):
            if len(text) < len(prev_text):
                continue
        if not re.match(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}', time_code):
            continue
        cleaned_blocks.append({
            'index': len(cleaned_blocks) + 1,
            'time': time_code,
            'text': text
        })
        prev_text = text

    with open(output_file, 'w', encoding='utf-8') as f:
        for i, block in enumerate(cleaned_blocks, 1):
            f.write(f'{i}\n')
            f.write(f'{block[\"time\"]}\n')
            f.write(f'{block[\"text\"]}\n\n')
    print(f'  已清理输出：{len(cleaned_blocks)} 条字幕')

clean_whisperx_srt(final_srt, final_en_srt)
"

echo "  已保存英文字幕：$FINAL_EN_SRT"

# Clean up intermediate files
rm -f "$FINAL_SRT" "$AUDIO_FILE" 2>/dev/null || true

echo "✅ WhisperX 转录完成（faster-whisper + whisperx 可选对齐）"
