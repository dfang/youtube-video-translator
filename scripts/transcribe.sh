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

# Resolve script paths before changing directory (supports relative invocation)
CALLER_PWD="$(pwd)"
if [[ "${BASH_SOURCE[0]}" = /* ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="$(cd "$CALLER_PWD/$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
BASE_DIR="$(dirname "$SCRIPT_DIR")"

cd "$WORK_DIR"

# Load environment variables from .env file (for ANTHROPIC_AUTH_TOKEN etc.)
ENV_FILE="$BASE_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "📄 加载环境变量：$ENV_FILE"
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    echo "  ANTHROPIC_AUTH_TOKEN: ${ANTHROPIC_AUTH_TOKEN:0:10}..."
else
    echo "⚠️ 未找到 .env 文件：$ENV_FILE"
fi

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

subtitle_needs_retranslation() {
    local srt_file="$1"
    python3 - "$srt_file" << 'PY'
import re
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
except Exception:
    print("0")
    sys.exit(0)

blocks = re.split(r'\n\n+', content.strip())
lines = []
for block in blocks:
    parts = [x.strip() for x in block.splitlines() if x.strip()]
    if len(parts) >= 3 and parts[0].isdigit() and "-->" in parts[1]:
        lines.append(" ".join(parts[2:]))

if not lines:
    print("0")
    sys.exit(0)

# Ignore very early intro lines; focus on body where batch issues often appear.
sample = lines[10:] if len(lines) > 15 else lines
bad = 0
for line in sample:
    en_letters = len(re.findall(r"[A-Za-z]", line))
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", line))
    if en_letters >= 6 and not has_cjk:
        bad += 1

ratio = bad / len(sample)
print("1" if (bad >= 3 and ratio >= 0.2) else "0")
PY
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
    NEED_RETRANSLATE=$(subtitle_needs_retranslation "$CHINESE_SRT")
    if [[ "$NEED_RETRANSLATE" == "1" ]]; then
        echo "  检测到中文字幕存在较多英文残留，自动重新翻译..."
        rm -f "$CHINESE_SRT"
        CHINESE_SRT=""
    fi
fi

if [[ -n "$CHINESE_SRT" ]]; then
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

# Claude-only translation
if [[ -z "$ANTHROPIC_AUTH_TOKEN" ]]; then
    echo "  ❌ 未配置 ANTHROPIC_AUTH_TOKEN，已禁用 Google Translate 回退"
    echo "  请在 .env 中配置 ANTHROPIC_AUTH_TOKEN 后重试"
    exit 1
fi
if [[ "${ANTHROPIC_BASE_URL:-}" == *"dashscope.aliyuncs.com"* ]]; then
    echo "  使用阿里云 Coding Plan 兼容接口进行翻译..."
else
    echo "  使用 Anthropic 兼容接口进行翻译..."
fi
echo "  API Base URL: ${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"

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
BASE_DIR = "$BASE_DIR"
ANTHROPIC_AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
TARGET_LANG_CODE = "$TARGET_LANG"
BATCH_SIZE = int(os.environ.get("TRANSLATE_BATCH_SIZE", "12"))
USER_MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip()

def is_dashscope_base(url):
    return "dashscope.aliyuncs.com" in (url or "").lower()

def build_model_candidates():
    if USER_MODEL:
        return [USER_MODEL]
    if is_dashscope_base(ANTHROPIC_BASE_URL):
        # For Aliyun Coding Plan, Claude model ids are usually unavailable.
        return ["qwen3.5-plus", "qwen3-coder-plus", "qwen-plus", "qwen-max", "kimi-k2-250711", "glm-4.6"]
    return ["claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219"]

def call_anthropic_compatible(prompt, model, max_tokens=1024, timeout=30):
    """Call Anthropic-compatible /v1/messages endpoint."""
    base = ANTHROPIC_BASE_URL.rstrip("/")
    url = f"{base}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    attempts = [
        {
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_AUTH_TOKEN,
            "anthropic-version": "2023-06-01",
        },
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ANTHROPIC_AUTH_TOKEN}",
            "anthropic-version": "2023-06-01",
        },
    ]

    errors = []
    for headers in attempts:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code >= 400:
                body = resp.text[:600].replace("\n", " ")
                errors.append(f"{resp.status_code} {body}")
                continue

            result = resp.json()
            content = result.get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "").strip()
                if text:
                    return text
            errors.append(f"invalid response: {str(result)[:300]}")
        except Exception as e:
            errors.append(str(e))

    raise RuntimeError(" | ".join(errors[-2:]))

def call_llm_api(prompt, max_tokens=1024, timeout=120):
    """Try candidate models until one works."""
    errors = []
    for model in build_model_candidates():
        try:
            return call_anthropic_compatible(prompt, model=model, max_tokens=max_tokens, timeout=timeout)
        except Exception as e:
            errors.append(f"{model}: {e}")
    raise RuntimeError(
        f"LLM API 调用失败（base={ANTHROPIC_BASE_URL}）。"
        f"请设置 ANTHROPIC_MODEL 指定可用模型。失败详情：{' || '.join(errors[-3:])}"
    )

def translate_text(text, target_lang="zh-CN"):
    """Translate text using Claude API only."""
    return translate_with_claude(text, target_lang)

def translate_with_claude(text, target_lang):
    """Translate text using Claude API"""
    try:
        lang_name = "简体中文" if target_lang.startswith("zh") else target_lang
        prompt = f"""你是一位专业的医学翻译。请将以下英文字幕翻译成{lang_name}。

翻译要求：
1. **所有内容必须翻译成中文**，不要保留任何英文单词（包括术语、缩写、专有名词）
2. 医学专业术语使用标准中文译名（如：ARDS→急性呼吸窘迫综合征，tidal volume→潮气量）
3. 翻译要自然流畅，符合中文口语表达习惯
4. 只输出翻译结果，不要任何解释或额外内容

英文原文：
{text}

中文翻译："""

        return call_llm_api(prompt, max_tokens=1024, timeout=30)
    except Exception as e:
        raise RuntimeError(f"LLM 翻译失败: {e}")

def translate_batch_with_claude(texts, target_lang):
    """Translate multiple subtitle lines in one Claude request."""
    if not texts:
        return []

    lang_name = "简体中文" if target_lang.startswith("zh") else target_lang
    numbered_lines = []
    for i, text in enumerate(texts, 1):
        clean_text = re.sub(r'\s+', ' ', text).strip()
        numbered_lines.append(f"[{i}] {clean_text}")

    prompt = f"""你是一位专业的医学翻译。请将以下英文字幕逐行翻译成{lang_name}。

翻译要求：
1. 所有内容必须翻译成中文，不要保留英文。
2. 医学术语使用标准中文译名。
3. 保持每一行编号不变，不要遗漏或新增行。
4. 每行只输出对应翻译，不要解释。

待翻译字幕：
{chr(10).join(numbered_lines)}

请严格按如下格式输出：
[1] 第一行译文
[2] 第二行译文
..."""

    output = call_llm_api(prompt, max_tokens=4096, timeout=60)

    parsed = {}
    for line in output.splitlines():
        m = re.match(r'^\[(\d+)\]\s*(.*)$', line.strip())
        if m:
            idx = int(m.group(1))
            parsed[idx] = m.group(2).strip()

    if len(parsed) != len(texts):
        raise ValueError(f"batch parse mismatch: expected {len(texts)}, got {len(parsed)}")

    return [parsed[i] for i in range(1, len(texts) + 1)]

def contains_cjk(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))

def should_retry_translation(original, translated, target_lang):
    """Heuristic: detect likely untranslated English output for zh targets."""
    if not target_lang.startswith("zh"):
        return False

    original = (original or "").strip()
    translated = (translated or "").strip()

    if not translated:
        return True
    if translated.lower() == original.lower():
        return True

    letter_chunks = re.findall(r'[A-Za-z\u4e00-\u9fff]', translated)
    total_letters = len(letter_chunks)
    en_letters = len(re.findall(r'[A-Za-z]', translated))
    en_ratio = (en_letters / total_letters) if total_letters else 0

    # Pure English output or mostly English mixed output
    if not contains_cjk(translated) and en_letters >= 6:
        return True
    if contains_cjk(translated) and en_letters >= 10 and en_ratio > 0.65:
        return True

    return False

def retranslate_if_needed(original_text, translated_text, target_lang):
    """Retry untranslated lines with single-line translation fallback chain."""
    if not should_retry_translation(original_text, translated_text, target_lang):
        return translated_text, False

    retry_text = translate_text(original_text, target_lang)
    if not should_retry_translation(original_text, retry_text, target_lang):
        return retry_text, True

    return retry_text, True

def translate_batch(texts, target_lang):
    """Translate a list of lines with Claude batch and single-line fallback."""
    if not texts:
        return []
    if len(texts) == 1:
        return [translate_text(texts[0], target_lang)]

    try:
        return translate_batch_with_claude(texts, target_lang)
    except Exception as e:
        print(f"    批量翻译失败，回退逐条 Claude：{e}")
        return [translate_text(text, target_lang) for text in texts]

def load_medical_vocab():
    """Load medical vocabulary from config file"""
    vocab = {}
    vocab_file = "$BASE_DIR/config/medical_vocab.txt"
    if os.path.exists(vocab_file):
        with open(vocab_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if ',' in line:
                        en, zh = line.split(',', 1)
                        vocab[en.strip().lower()] = zh.strip()
    return vocab

def post_process_translation(text, vocab):
    """Post-process translation to replace remaining English terms"""
    if not vocab:
        return text

    # Sort by length (longer first) to avoid partial replacements
    sorted_terms = sorted(vocab.keys(), key=len, reverse=True)

    result = text
    for en_term in sorted_terms:
        # Case-insensitive replacement
        pattern = re.compile(re.escape(en_term), re.IGNORECASE)
        if pattern.search(result):
            zh_translation = vocab[en_term]
            result = pattern.sub(zh_translation, result)

    # Also clean up common leftover English words
    common_leftovers = {
        r'\babout\b': '关于',
        r'\bfrom\b': '从',
        r'\bthis\b': '这个',
        r'\bthat\b': '那个',
        r'\bthese\b': '这些',
        r'\bthose\b': '那些',
        r'\bwith\b': '与',
        r'\binto\b': '进入',
        r'\bthrough\b': '通过',
        r'\bbetween\b': '之间',
        r'\bamong\b': '在...之中',
        r'\bconcept of\b': '...的概念',
        r'\btype of\b': '...类型',
        r'\bkind of\b': '种类',
    }
    for pattern, replacement in common_leftovers.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Fix common translation errors for medical terms
    wrong_translations = {
        '机械动力': '机械能',
        '预防绒毛': '预防呼吸机诱导肺损伤',
        '隧道容量': '潮气量',
        '窥视': '呼气末正压',
        '低台容积通气': '低潮气量通气',
        '呼吸机引起的肺损伤': '呼吸机诱导的肺损伤',
        '新英格兰杂志': '新英格兰医学杂志',
        '能源概念': '能量概念',
    }
    for wrong, right in wrong_translations.items():
        result = result.replace(wrong, right)

    return result

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

# Load medical vocabulary for post-processing
vocab = load_medical_vocab()
if vocab:
    print(f"  已加载 {len(vocab)} 个医学词汇用于后处理")

translated_blocks = []
original_blocks = []
start_time = __import__('time').time()
for block in blocks:
    original_blocks.append({
        'index': block['index'],
        'time': block['time'],
        'text': list(block['text']),
    })
    translated_blocks.append({
        'index': block['index'],
        'time': block['time'],
        'text': list(block['text']),
    })

translatable = []
for idx, block in enumerate(blocks):
    original_text = ' '.join(block['text']).strip()
    if len(original_text) >= 2:
        translatable.append((idx, original_text))

total = len(translatable)
retried_lines = 0
if total == 0:
    print("  无需翻译的有效字幕内容")
else:
    for start in range(0, total, BATCH_SIZE):
        batch_items = translatable[start:start + BATCH_SIZE]
        batch_texts = [item[1] for item in batch_items]

        translated_texts = translate_batch(batch_texts, "$TARGET_LANG")

        for (block_idx, original_text), translated_text in zip(batch_items, translated_texts):
            translated_text, retried = retranslate_if_needed(original_text, translated_text, "$TARGET_LANG")
            if retried:
                retried_lines += 1
            translated_text = post_process_translation(translated_text, vocab)
            # Always store Chinese-only for TTS compatibility.
            translated_blocks[block_idx]['text'] = [translated_text]

        processed = start + len(batch_items)
        elapsed = __import__('time').time() - start_time
        avg_time = elapsed / processed if processed else 0
        remaining = (total - processed) * avg_time
        progress = processed / total * 100
        print(f"    翻译 {processed}/{total} ({progress:.1f}%) - 剩余 {remaining:.0f}s   ", end='\r', flush=True)


print(f"\n  翻译完成！")
if retried_lines > 0:
    print(f"  自动补翻英文残留：{retried_lines} 条")

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
