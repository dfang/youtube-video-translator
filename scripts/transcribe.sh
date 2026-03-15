#!/bin/bash
# Transcribe/Translate subtitles
# Usage: ./transcribe.sh <WORK_DIR> <TARGET_LANG> <SUBTITLE_TYPE>
# SUBTITLE_TYPE: chinese (default) or bilingual

set -e

WORK_DIR="$1"
TARGET_LANG="${2:-zh-CN}"
SUBTITLE_TYPE="${3:-chinese}"  # chinese or bilingual

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
    copy_chinese_subtitle "$ZH_HANS_VTT" "$VIDEO_BASE.zh-CN.srt"

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
    BASE_NAME="${VTT_FILE%.*}"

    # Convert VTT to SRT
    echo "  转换 VTT 为 SRT..."
    ffmpeg -i "$VTT_FILE" "$BASE_NAME.srt" 2>/dev/null || \
    cat "$VTT_FILE" | sed 's/WEBVTT//g' | sed 's/Kind:[^ ]*//g' | sed 's/Default:[^ ]*//g' > "$BASE_NAME.tmp.srt" && \
    mv "$BASE_NAME.tmp.srt" "$BASE_NAME.srt"

    SRT_FILE="$BASE_NAME.srt"
elif [[ -n "$SRT_FILE" ]]; then
    echo "  找到英文字幕（SRT 格式，无需转换）：$SRT_FILE"
    BASE_NAME="${SRT_FILE%.*}"
else
    echo "  未找到字幕文件，需要自动转录"
    echo "  请安装 whisper 或手动提供字幕"
    exit 1
fi

# Translate subtitles from English to target language
echo "  翻译字幕为 $TARGET_LANG..."
if [[ "$SUBTITLE_TYPE" == "bilingual" ]]; then
    echo "  生成中英文双语字幕..."
fi
python3 << EOF
import re
import requests
import time

def translate_text(text, target_lang="zh-CN"):
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

        # Extract translation from nested structure
        translation = ''.join([sentence[0] for sentence in result[0] if sentence[0]])
        return translation
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
for i, block in enumerate(blocks):
    original_text = ' '.join(block['text'])
    original_blocks.append(block.copy())

    # Skip very short texts
    if len(original_text.strip()) < 2:
        translated_blocks.append(block)
        continue

    # Translate
    print(f"    翻译 {i+1}/{len(blocks)}...", end='\r')
    translated_text = translate_text(original_text, "$TARGET_LANG")

    # Update block
    if "$SUBTITLE_TYPE" == "bilingual":
        # For bilingual: put Chinese first, then English in parentheses
        block['text'] = [translated_text, original_text]
    else:
        # Chinese only
        block['text'] = [translated_text]
    translated_blocks.append(block)

    # Rate limiting
    time.sleep(0.5)

print(f"  翻译完成！")

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
