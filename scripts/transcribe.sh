#!/bin/bash
# Transcribe/Translate subtitles
# Usage: ./transcribe.sh <WORK_DIR> <TARGET_LANG> <SUBTITLE_TYPE> <SUBTITLE_SOURCE> [WHISPER_MODEL] [VOCAB_FILE]
# SUBTITLE_TYPE: chinese (default) or bilingual
# SUBTITLE_SOURCE: download (default), whisper, or whisperx
# WHISPER_MODEL: medium (default), tiny, base, small, large-v3
# VOCAB_FILE: optional path to vocabulary file or built-in name (e.g., medical)

set -e

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
SUBTITLE_TYPE="${3:-chinese}"  # chinese or bilingual
SUBTITLE_SOURCE="${4:-download}"  # download, whisper, or whisperx
WHISPER_MODEL="${5:-large-v3-turbo}"  # whisper model
VOCAB_FILE="${6:-medical}"  # default: medical built-in vocabulary

cd "$WORK_DIR"

# Helper function to convert VTT to SRT
convert_vtt_to_srt() {
    local vtt_file="$1"
    local base_name="${vtt_file%.*}"

    # Check if target SRT already exists (not just any .srt)
    if [[ -f "$base_name.srt" ]] && [[ "$base_name.srt" != "$vtt_file" ]]; then
        echo "  SRT 文件已存在，跳过转换"
        return 0
    fi

    echo "  转换 VTT 为 SRT..."
    # Try ffmpeg first
    if ffmpeg -i "$vtt_file" "$base_name.srt" 2>/dev/null; then
        echo "  使用 ffmpeg 转换成功"
        return 0
    fi

    # Fallback to sed
    cat "$vtt_file" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$base_name.tmp.srt"
    mv "$base_name.tmp.srt" "$base_name.srt"
    echo "  使用 sed 转换成功"
}

# Helper function to copy/rename Chinese subtitle
copy_chinese_subtitle() {
    local source_file="$1"
    local target_file="$2"

    if [[ -f "$target_file" ]]; then
        echo "  中文字幕已存在：$target_file"
        return 0
    fi

    # Check if source is already SRT
    if [[ "$source_file" == *.srt ]]; then
        # Clean YouTube translated subtitle format (remove duplicate lines)
        python3 << CLEAN_EOF
import re

def time_to_ms(t):
    h, m, s = t.replace(',', '.').split(':')
    return int(h)*3600000 + int(m)*60000 + int(float(s)*1000)

def ms_to_time(ms):
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

srt_file = "$source_file"
output_file = "$target_file"

with open(srt_file, 'r', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'\n\n+', content.strip())

parsed = []
for block in blocks:
    lines = block.strip().split('\n')
    if len(lines) < 3:
        continue
    try:
        index = int(lines[0])
        time_code = lines[1]
        text = ' '.join(lines[2:]).strip()
    except:
        continue
    time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_code)
    if time_match:
        start, end = time_match.groups()
        parsed.append({
            'start': start, 'end': end,
            'start_ms': time_to_ms(start), 'end_ms': time_to_ms(end),
            'text': text
        })

if not parsed:
    # No valid parsed blocks, just copy
    import shutil
    shutil.copy(srt_file, output_file)
    exit(0)

# Extract full text by removing duplicate prefixes
full_parts = []
prev_text = ""
for block in parsed:
    text = block['text']
    if prev_text == "":
        full_parts.append(text)
    elif text.startswith(prev_text):
        new_part = text[len(prev_text):]
        if new_part.strip():
            full_parts.append(new_part.strip())
    prev_text = text

full_text = ''.join(full_parts)
# Clean up spaces around Chinese punctuation
import re
full_text = re.sub(r'\s*([.!?.!?,,,;:""''())])\s*', r'\1', full_text)
full_text = re.sub(r'\s+', ' ', full_text).strip()

# Split by sentence punctuation
sentences = re.split(r'([.!?.!?])', full_text)
clean_sentences = []
for i in range(0, len(sentences)-1, 2):
    sentence = sentences[i].strip()
    punct = sentences[i+1] if i+1 < len(sentences) else ''
    if sentence or punct:
        clean_sentences.append(sentence + punct)

# Remove very short sentences
clean_sentences = [s for s in clean_sentences if len(s.strip()) > 3]

# Calculate timing
video_start_ms = parsed[0]['start_ms']
video_end_ms = parsed[-1]['end_ms']
video_duration = video_end_ms - video_start_ms
total_chars = len(full_text)

output_srt = []
for i, sentence in enumerate(clean_sentences):
    search = sentence[:min(20, len(sentence))]
    pos = full_text.find(search)

    if pos >= 0:
        progress = pos / total_chars
        start_ms = int(video_start_ms + progress * video_duration)
        duration_ms = max(1500, int(len(sentence) * 220))
        end_ms = start_ms + duration_ms
    else:
        start_ms = video_start_ms
        duration_ms = max(1500, int(len(sentence) * 220))
        end_ms = start_ms + duration_ms

    start_time = ms_to_time(start_ms)
    end_time = ms_to_time(end_ms)

    output_srt.append(str(i+1))
    output_srt.append(f"{start_time} --> {end_time}")
    output_srt.append(sentence)
    output_srt.append('')

with open(output_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_srt))

print(f"  已清理 YouTube 字幕格式：{len(clean_sentences)} 条句子")
CLEAN_EOF
    else
        # Convert VTT to SRT first
        convert_vtt_to_srt "$source_file"
        local base_name="${source_file%.*}"
        # Also clean VTT-based subtitles
        python3 << CLEAN_EOF
import re

def time_to_ms(t):
    h, m, s = t.replace(',', '.').split(':')
    return int(h)*3600000 + int(m)*60000 + int(float(s)*1000)

def ms_to_time(ms):
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

vtt_file = "$base_name.vtt"
output_file = "$target_file"

with open(vtt_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove WEBVTT header and style tags
content = re.sub(r'WEBVTT[^ ]*', '', content)
content = re.sub(r'Kind:[^ ]*', '', content)
content = re.sub(r'Default:[^ ]*', '', content)
content = re.sub(r'<[^>]+>', '', content)  # Remove HTML-like tags

blocks = re.split(r'\n\n+', content.strip())

parsed = []
for block in blocks:
    lines = block.strip().split('\n')
    if len(lines) < 2:
        continue
    try:
        time_code = lines[0]
        text = ' '.join(lines[1:]).strip()
    except:
        continue
    time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', time_code)
    if time_match:
        start, end = time_match.groups()
        parsed.append({
            'start': start, 'end': end,
            'start_ms': time_to_ms(start), 'end_ms': time_to_ms(end),
            'text': text
        })

if not parsed:
    # Fallback: copy the already-converted SRT file if it exists
    import os, shutil
    srt_converted = vtt_file.replace('.vtt', '.srt')
    if os.path.exists(srt_converted):
        shutil.copy(srt_converted, output_file)
        print(f"  VTT 解析失败，已复制 SRT 文件：{output_file}")
        exit(0)
    else:
        print(f"  VTT 解析失败且无 SRT 文件：{vtt_file}")
        exit(1)

# Extract full text by removing duplicate prefixes
full_parts = []
prev_text = ""
for block in parsed:
    text = block['text']
    if prev_text == "":
        full_parts.append(text)
    elif text.startswith(prev_text):
        new_part = text[len(prev_text):]
        if new_part.strip():
            full_parts.append(new_part.strip())
    prev_text = text

full_text = ''.join(full_parts)
full_text = re.sub(r'\s*([.!?.!?,,,;:""''())])\s*', r'\1', full_text)
full_text = re.sub(r'\s+', ' ', full_text).strip()

sentences = re.split(r'([.!?.!?])', full_text)
clean_sentences = []
for i in range(0, len(sentences)-1, 2):
    sentence = sentences[i].strip()
    punct = sentences[i+1] if i+1 < len(sentences) else ''
    if sentence or punct:
        clean_sentences.append(sentence + punct)

clean_sentences = [s for s in clean_sentences if len(s.strip()) > 3]

video_start_ms = parsed[0]['start_ms']
video_end_ms = parsed[-1]['end_ms']
video_duration = video_end_ms - video_start_ms
total_chars = len(full_text)

output_srt = []
for i, sentence in enumerate(clean_sentences):
    search = sentence[:min(20, len(sentence))]
    pos = full_text.find(search)

    if pos >= 0:
        progress = pos / total_chars
        start_ms = int(video_start_ms + progress * video_duration)
        duration_ms = max(1500, int(len(sentence) * 220))
        end_ms = start_ms + duration_ms
    else:
        start_ms = video_start_ms
        duration_ms = max(1500, int(len(sentence) * 220))
        end_ms = start_ms + duration_ms

    start_time = ms_to_time(start_ms)
    end_time = ms_to_time(end_ms)

    output_srt.append(str(i+1))
    output_srt.append(f"{start_time} --> {end_time}")
    output_srt.append(sentence)
    output_srt.append('')

with open(output_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_srt))

print(f"  已清理 YouTube 字幕格式：{len(clean_sentences)} 条句子")
CLEAN_EOF
    fi

    echo "  已复制中文字幕：$target_file"
}

echo "  检测字幕文件..."

# In bilingual mode or whisperx mode, always regenerate subtitles to ensure clean output
if [[ "$SUBTITLE_TYPE" == "bilingual" || "$SUBTITLE_SOURCE" == "whisperx" ]]; then
    # Remove old Chinese subtitle files to force regeneration
    # Don't remove *.en.srt in download mode as it's needed as source for translation
    rm -f *.zh-CN.srt *.en.only.srt 2>/dev/null || true
    if [[ "$SUBTITLE_SOURCE" == "whisperx" ]]; then
        echo "  whisperx 模式：已清理旧字幕文件，将重新转录"
    else
        echo "  双语模式：已清理旧字幕文件，将重新生成"
    fi
fi

# Priority 1: Check if Chinese subtitle already exists (zh-CN.srt)
CHINESE_SRT=$(find . -maxdepth 1 -name "*.zh-CN.srt" -type f | head -1)
if [[ -n "$CHINESE_SRT" ]]; then
    echo "  找到已有中文字幕：$CHINESE_SRT"
    SRT_FILE="$CHINESE_SRT"
    BASE_NAME="${SRT_FILE%.*}"
    BASE_NAME="${BASE_NAME%.$TARGET_LANG}"

    # If bilingual mode, still need to prepare English subtitle for TTS
    if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
        echo "  双语模式：继续处理英文字幕..."
        VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
        VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
        EN_VTT=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
        if [[ -n "$EN_VTT" ]]; then
            echo "  找到英文字幕：$EN_VTT"
            if ffmpeg -i "$EN_VTT" "$VIDEO_BASE.en.srt" 2>/dev/null; then
                echo "  使用 ffmpeg 转换英文字幕成功"
            else
                cat "$EN_VTT" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$VIDEO_BASE.en.tmp.srt"
                mv "$VIDEO_BASE.en.tmp.srt" "$VIDEO_BASE.en.srt"
                echo "  使用 sed 转换英文字幕成功"
            fi
            echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
        fi
        echo "✅ 字幕处理完成（双语模式）"
        exit 0
    fi

    echo "  跳过翻译步骤"
    echo "✅ 字幕处理完成（使用已有中文字幕）"
    exit 0
fi

# Priority 2: Check for zh-Hans.vtt or zh-Hans.srt (Simplified Chinese from YouTube)
ZH_HANS_VTT=$(find . -maxdepth 1 -name "*.zh-Hans.vtt" -type f | head -1)
if [[ -n "$ZH_HANS_VTT" ]]; then
    echo "  找到简体中文字幕：$ZH_HANS_VTT"
    # Get base name from video file
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    # Use dedup_subtitle.py to clean YouTube highlight-style subtitles
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/dedup_subtitle.py" "$ZH_HANS_VTT" "$VIDEO_BASE.zh-CN.srt"

    # If bilingual mode, also need to prepare English subtitle for TTS
    if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
        echo "  双语模式：继续处理英文字幕..."
        # Continue to process English subtitle below
        # Convert English VTT to SRT for TTS
        EN_VTT=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
        if [[ -n "$EN_VTT" ]]; then
            echo "  找到英文字幕：$EN_VTT"
            if ffmpeg -i "$EN_VTT" "$VIDEO_BASE.en.srt" 2>/dev/null; then
                echo "  使用 ffmpeg 转换英文字幕成功"
            else
                cat "$EN_VTT" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$VIDEO_BASE.en.tmp.srt"
                mv "$VIDEO_BASE.en.tmp.srt" "$VIDEO_BASE.en.srt"
                echo "  使用 sed 转换英文字幕成功"
            fi
            echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
        fi
        # Bilingual mode done - English subtitle ready for TTS, Chinese subtitle ready for display
        echo "✅ 字幕处理完成（双语模式）"
        exit 0
    else
        echo "✅ 字幕处理完成（使用下载的中文字幕）"
        exit 0
    fi
fi

ZH_HANS_SRT=$(find . -maxdepth 1 -name "*.zh-Hans.srt" -type f | head -1)
if [[ -n "$ZH_HANS_SRT" ]]; then
    echo "  找到简体中文字幕：$ZH_HANS_SRT"
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    cp "$ZH_HANS_SRT" "$VIDEO_BASE.zh-CN.srt"

    # If bilingual mode, also need to prepare English subtitle for TTS
    if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
        echo "  双语模式：继续处理英文字幕..."
        # Convert English VTT to SRT for TTS if needed
        EN_VTT=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
        if [[ -n "$EN_VTT" ]]; then
            echo "  找到英文字幕：$EN_VTT"
            if ffmpeg -i "$EN_VTT" "$VIDEO_BASE.en.srt" 2>/dev/null; then
                echo "  使用 ffmpeg 转换英文字幕成功"
            else
                cat "$EN_VTT" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$VIDEO_BASE.en.tmp.srt"
                mv "$VIDEO_BASE.en.tmp.srt" "$VIDEO_BASE.en.srt"
                echo "  使用 sed 转换英文字幕成功"
            fi
            echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
        fi
        echo "✅ 字幕处理完成（双语模式）"
        exit 0
    else
        echo "✅ 字幕处理完成（使用下载的中文字幕）"
        exit 0
    fi
fi

# Priority 3: Check for zh-Hant.vtt or zh-Hant.srt (Traditional Chinese)
ZH_HANT_VTT=$(find . -maxdepth 1 -name "*.zh-Hant.vtt" -type f | head -1)
if [[ -n "$ZH_HANT_VTT" ]]; then
    echo "  找到繁体中文字幕：$ZH_HANT_VTT"
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    copy_chinese_subtitle "$ZH_HANT_VTT" "$VIDEO_BASE.zh-CN.srt"

    # If bilingual mode, also need to prepare English subtitle for TTS
    if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
        echo "  双语模式：继续处理英文字幕..."
        EN_VTT=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
        if [[ -n "$EN_VTT" ]]; then
            echo "  找到英文字幕：$EN_VTT"
            if ffmpeg -i "$EN_VTT" "$VIDEO_BASE.en.srt" 2>/dev/null; then
                echo "  使用 ffmpeg 转换英文字幕成功"
            else
                cat "$EN_VTT" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$VIDEO_BASE.en.tmp.srt"
                mv "$VIDEO_BASE.en.tmp.srt" "$VIDEO_BASE.en.srt"
                echo "  使用 sed 转换英文字幕成功"
            fi
            echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
        fi
        echo "✅ 字幕处理完成（双语模式）"
        exit 0
    fi

    echo "✅ 字幕处理完成（使用下载的中文字幕，繁转简可能需要额外处理）"
    exit 0
fi

ZH_HANT_SRT=$(find . -maxdepth 1 -name "*.zh-Hant.srt" -type f | head -1)
if [[ -n "$ZH_HANT_SRT" ]]; then
    echo "  找到繁体中文字幕：$ZH_HANT_SRT"
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    cp "$ZH_HANT_SRT" "$VIDEO_BASE.zh-CN.srt"

    # If bilingual mode, also need to prepare English subtitle for TTS
    if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
        echo "  双语模式：继续处理英文字幕..."
        EN_VTT=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
        if [[ -n "$EN_VTT" ]]; then
            echo "  找到英文字幕：$EN_VTT"
            if ffmpeg -i "$EN_VTT" "$VIDEO_BASE.en.srt" 2>/dev/null; then
                echo "  使用 ffmpeg 转换英文字幕成功"
            else
                cat "$EN_VTT" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$VIDEO_BASE.en.tmp.srt"
                mv "$VIDEO_BASE.en.tmp.srt" "$VIDEO_BASE.en.srt"
                echo "  使用 sed 转换英文字幕成功"
            fi
            echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
        fi
        echo "✅ 字幕处理完成（双语模式）"
        exit 0
    fi

    echo "✅ 字幕处理完成（使用下载的中文字幕）"
    exit 0
fi

# Priority 4: No Chinese subtitles, need to translate from English
echo "  未找到中文字幕，准备翻译英文字幕..."

# Find English subtitle files - use find to handle filenames with spaces
VTT_FILE=$(find . -maxdepth 1 -name "*.en.vtt" -type f | head -1)
SRT_FILE=$(find . -maxdepth 1 -name "*.en.srt" -type f | head -1)

if [[ -n "$VTT_FILE" ]]; then
    echo "  找到英文字幕：$VTT_FILE"
    # Get base name from video file to ensure correct output naming
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    BASE_NAME="$VIDEO_BASE"

    # Convert VTT to SRT
    echo "  转换 VTT 为 SRT..."
    if ! ffmpeg -i "$VTT_FILE" "$BASE_NAME.srt" 2>/dev/null; then
        echo "  ffmpeg 转换失败，使用 sed 手动转换..."
        cat "$VTT_FILE" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$BASE_NAME.tmp.srt"
        mv "$BASE_NAME.tmp.srt" "$BASE_NAME.srt"
    fi

    SRT_FILE="$BASE_NAME.srt"
    echo "  已加载英文字幕：$SRT_FILE"
elif [[ -n "$SRT_FILE" ]]; then
    echo "  找到英文字幕（SRT 格式，无需转换）：$SRT_FILE"
    # Get base name from video file to ensure correct output naming
    VIDEO_BASE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
    VIDEO_BASE="${VIDEO_BASE%.original.mp4}"
    BASE_NAME="$VIDEO_BASE"
else
    echo "  未找到字幕文件，需要自动转录"

    # Check if whisper mode is enabled
    if [[ "$SUBTITLE_SOURCE" == "whisper" || "$SUBTITLE_SOURCE" == "whisperx" ]]; then
        VIDEO_FILE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
        if [[ -z "$VIDEO_FILE" ]]; then
            echo "  ❌ 未找到视频文件"
            exit 1
        fi

        # Get base name from video
        VIDEO_BASE="${VIDEO_FILE%.original.mp4}"

        if [[ "$SUBTITLE_SOURCE" == "whisperx" ]]; then
            # Use faster-whisper + whisperx alignment
            echo "  使用 faster-whisper + whisperx 进行转录和对齐..."
            SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            bash "$SCRIPT_DIR/whisperx-transcribe.sh" "$WORK_DIR" "en" "$WHISPER_MODEL" "$VOCAB_FILE"
        elif command -v faster-whisper &> /dev/null; then
            echo "  使用 faster-whisper 进行转录（速度更快）..."
            # Build initial prompt from vocabulary if provided
            VOCAB_ARGS=""
            if [[ -n "$VOCAB_FILE" ]]; then
                if [[ "$VOCAB_FILE" == "medical" ]]; then
                    VOCAB_ARGS="--initial-prompt \"The following medical terms may appear: ARDS, acute respiratory distress syndrome, COVID-19, SARS, MERS, ICU, ventilator, intubation, hypoxemia, pulmonary, respiratory, pneumonia, sepsis, cytokine storm, ACE2, viral load, PCR, COPD, asthma\""
                elif [[ "$VOCAB_FILE" == "tech" ]]; then
                    VOCAB_ARGS="--initial-prompt \"The following tech terms may appear: API, SDK, CLI, GUI, HTTP, HTTPS, Kubernetes, Docker, container, microservice, JavaScript, TypeScript, Python, React, WebSocket, REST, GraphQL, JWT, OAuth\""
                elif [[ -f "$VOCAB_FILE" ]]; then
                    VOCAB_ARGS="--initial-prompt-file $VOCAB_FILE"
                fi
            fi
            faster-whisper "$VIDEO_FILE" --model "$WHISPER_MODEL" --output_dir . --output_format srt --language en $VOCAB_ARGS
            if [[ -f "${VIDEO_BASE}.srt" ]]; then
                mv "${VIDEO_BASE}.srt" "$VIDEO_BASE.en.srt"
            fi
        elif command -v whisper &> /dev/null; then
            echo "  使用 Whisper 进行转录（这可能需要几分钟）..."
            whisper "$VIDEO_FILE" --model base --output_dir . --output_format srt --language en
        else
            echo "  ❌ 未找到 whisper 或 faster-whisper 命令"
            echo "  请安装："
            echo "    pip install openai-whisper"
            echo "    或 pip install faster-whisper（推荐，速度更快）"
            echo "    或 pip install whisperx（最佳质量，单词级对齐）"
            exit 1
        fi

        # Rename output file for whisper mode (whisperx handles its own output)
        if [[ "$SUBTITLE_SOURCE" != "whisperx" ]]; then
            # Rename output file - Whisper may output to different locations
            if [[ -f "video.srt" ]]; then
                mv "video.srt" "$VIDEO_BASE.en.srt"
                echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
            elif [[ -f "${VIDEO_BASE}.original.srt" ]]; then
                mv "${VIDEO_BASE}.original.srt" "$VIDEO_BASE.en.srt"
                echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
            elif [[ -f "${VIDEO_BASE}.srt" ]]; then
                mv "${VIDEO_BASE}.srt" "$VIDEO_BASE.en.srt"
                echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
            elif [[ -f "$VIDEO_BASE.en.srt" ]]; then
                echo "  已保存英文字幕：$VIDEO_BASE.en.srt"
            else
                echo "  ❌ Whisper 转录失败，未生成字幕文件"
                exit 1
            fi
        fi

        # Set SRT_FILE for translation step
        SRT_FILE="$VIDEO_BASE.en.srt"
        BASE_NAME="$VIDEO_BASE"
        if [[ "$SUBTITLE_SOURCE" == "whisperx" ]]; then
            echo "  ✅ WhisperX 转录完成（单词级对齐，时间轴精确）"
        else
            echo "  ✅ Whisper 转录完成（无高亮字幕，时间轴干净）"
        fi
    else
        echo "  请安装 whisper 或手动提供字幕"
        echo "  使用 --subtitle-source=whisper 参数可使用 Whisper 本地转录"
        exit 1
    fi
fi

# Step: Preview and confirm transcription (for whisper/whisperx modes)
if [[ "$SUBTITLE_SOURCE" == "whisper" || "$SUBTITLE_SOURCE" == "whisperx" ]]; then
    echo ""
    echo "🔍 转录完成，预览前 15 条字幕："
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    head -n 50 "$SRT_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Check if non-interactive mode
    if [[ -n "$AUTO_CONFIRM" ]] || [[ ! -t 0 ]]; then
        echo "⚡ 非交互模式，自动继续..."
    else
        echo ""
        echo "❓ 是否发现专业术语识别错误？"
        echo "   [y] 继续 (识别正确)"
        echo "   [e] 编辑字幕 (手动校正识别错误)"
        echo "   [q] 退出脚本"
        read -p "请输入 [y/e/q]: " PREVIEW_CHOICE

        case "$PREVIEW_CHOICE" in
            [qQ])
                echo "🛑 用户选择退出。"
                exit 0
                ;;
            [eE])
                echo "📝 请在另一个终端或编辑器中修改：$SRT_FILE"
                echo "💡 提示：可以使用以下命令快速编辑："
                echo "   nano \"$SRT_FILE\""
                echo "   或 code \"$SRT_FILE\""
                read -p "修改完成后，请按回车键继续翻译..."
                ;;
            *)
                echo "🚀 继续翻译..."
                ;;
        esac
    fi
fi

# Translate subtitles from English to target language
echo "  翻译字幕为 $TARGET_LANG..."

# Detect translation method
TRANSLATE_METHOD="google"
if [[ -n "$ANTHROPIC_AUTH_TOKEN" ]]; then
    TRANSLATE_METHOD="claude"
    echo "  使用 Claude API 进行翻译..."
    echo "  API Base URL: ${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
else
    echo "  未配置 ANTHROPIC_AUTH_TOKEN，使用 Google Translate 免费翻译"
fi

# 人工确认步骤：显示预览并询问（仅当不是 whisper/whisperx 模式且未设置 AUTO_CONFIRM）
if [[ "$SUBTITLE_SOURCE" != "whisper" && "$SUBTITLE_SOURCE" != "whisperx" ]]; then
    # 检测是否为交互模式，非交互模式自动跳过确认
    EN_PREVIEW=$(head -n 20 "$SRT_FILE" 2>/dev/null || echo "无法读取文件")
    echo "--------------------------------------------------"
    echo "🔍 英文字幕预览 ($SRT_FILE):"
    echo "$EN_PREVIEW"
    echo "--------------------------------------------------"

    # 检查是否为非交互模式（通过环境变量或 test -t 0）
    if [[ -n "$AUTO_CONFIRM" ]] || [[ ! -t 0 ]]; then
        echo "⚡ 非交互模式，自动继续翻译..."
        CONFIRM_CHOICE="y"
    else
        echo "❓ 英文字幕看起来是否有重复（如滚动高亮模式）？"
        echo "   [y] 继续翻译 (默认)"
        echo "   [e] 编辑字幕 (此时你可以手动修改 $WORK_DIR 目录下的文件)"
        echo "   [q] 退出脚本"
        read -p "请输入 [y/e/q]: " CONFIRM_CHOICE
    fi

    case "$CONFIRM_CHOICE" in
        [qQ])
            echo "🛑 用户选择退出。"
            exit 0
            ;;
        [eE])
            echo "📝 请在另一个终端或编辑器中修改：$WORK_DIR/$SRT_FILE"
            read -p "修改完成后，请按回车键继续翻译..."
            ;;
        *)
            echo "🚀 继续翻译..."
            ;;
    esac
fi

if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
    echo "  生成中英文双语字幕..."
fi
python3 << EOF
import re
import requests
import time
import os

# Translation configuration
TRANSLATE_METHOD = "$TRANSLATE_METHOD"
ANTHROPIC_AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
TARGET_LANG_CODE = "$TARGET_LANG"

def translate_text(text, target_lang="zh-CN"):
    """Translate text using Claude API or Google Translate"""

    if TRANSLATE_METHOD == "claude" and ANTHROPIC_AUTH_TOKEN:
        return translate_with_claude(text, target_lang)
    else:
        return translate_with_google(text, target_lang)

def translate_with_claude(text, target_lang):
    """Translate text using Claude API"""
    try:
        lang_name = "Chinese" if target_lang.startswith("zh") else target_lang
        prompt = f"""Translate the following English text to {lang_name}. Only output the translation, no explanations:

{text}"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ANTHROPIC_AUTH_TOKEN}",
            "anthropic-version": "2023-06-01"
        }

        data = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            headers=headers,
            json=data,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

        translation = result["content"][0]["text"].strip()
        return translation
    except Exception as e:
        print(f"    Claude 翻译失败：{e}，回退到 Google Translate")
        return translate_with_google(text, target_lang)

def translate_with_google(text, target_lang):
    """Translate text using Google Translate"""
    try:
        url = "https://translate.googleapis.com/translate_a/t"
        params = {
            'client': 'gtx',
            'sl': 'auto',
            'tl': target_lang.split('-')[0],
            'dt': 't',
            'q': text
        }
        response = requests.get(url, params=params, timeout=10)
        result = response.json()

        if isinstance(result, list) and len(result) > 0:
            translation_parts = []
            for item in result:
                if isinstance(item, list) and len(item) > 0:
                    translation_parts.append(item[0])
            if translation_parts:
                return ''.join(translation_parts)

        return text
    except Exception as e:
        print(f"    翻译失败：{e}")
        return text

def parse_srt(srt_content):
    """Parse SRT content into blocks"""
    blocks = []
    current_block = {'index': 0, 'time': '', 'text': []}

    for line in srt_content.strip().split('\n'):
        line = line.strip()
        if not line:
            if current_block['text']:
                blocks.append(current_block)
            current_block = {'index': 0, 'time': '', 'text': []}
            continue

        if line.isdigit():
            current_block['index'] = int(line)
        elif '-->' in line:
            current_block['time'] = line
        else:
            current_block['text'].append(line)

    if current_block['text']:
        blocks.append(current_block)

    return blocks

def format_srt(blocks):
    """Format blocks back to SRT"""
    output = []
    for i, block in enumerate(blocks, 1):
        output.append(str(i))
        output.append(block['time'])
        output.append('\n'.join(block['text']))
        output.append('')
    return '\n'.join(output)

# Read original SRT
with open("$SRT_FILE", 'r', encoding='utf-8', errors='ignore') as f:
    srt_content = f.read()

# Parse and translate
blocks = parse_srt(srt_content)
print(f"  共 {len(blocks)} 条字幕")

translated_blocks = []
original_blocks = []
start_time = __import__('time').time()

for i, block in enumerate(blocks):
    original_text = ' '.join(block['text'])
    original_blocks.append(block.copy())

    # Skip very short texts
    if len(original_text.strip()) < 2:
        translated_blocks.append(block)
        continue

    # Translate
    elapsed = __import__('time').time() - start_time
    avg_time = elapsed / (i + 1) if i > 0 else 0
    remaining = (len(blocks) - i - 1) * avg_time
    progress = (i + 1) / len(blocks) * 100
    print(f"    翻译 {i+1}/{len(blocks)} ({progress:.1f}%) - 剩余 {remaining:.0f}s   ", end='\r', flush=True)
    translated_text = translate_text(original_text, "$TARGET_LANG")

    # Update block - always store Chinese-only for TTS compatibility
    # Bilingual display will be handled by merge.sh when creating ASS subtitles
    block['text'] = [translated_text]
    translated_blocks.append(block)

    # Rate limiting (only for Google Translate)
    if TRANSLATE_METHOD != "claude":
        time.sleep(0.5)

print(f"\n  翻译完成！")

# Write translated SRT
output_file = "$BASE_NAME.$TARGET_LANG.srt"
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(format_srt(translated_blocks))

print(f"  已保存：$output_file")

# Also save English-only subtitle file for TTS generation
if "$SUBTITLE_TYPE" == "bilingual":
    en_output_file = "$BASE_NAME.en.only.srt"
    with open(en_output_file, 'w', encoding='utf-8') as f:
        f.write(format_srt(original_blocks))
    print(f"  已保存英文字幕：$en_output_file")
EOF

echo "✅ 字幕处理完成"
