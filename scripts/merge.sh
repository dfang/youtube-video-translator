#!/bin/bash
# Merge video and dubbed audio
# Usage: ./merge.sh <WORK_DIR> [SUBTITLE_TYPE]
# SUBTITLE_TYPE: chinese (default) or bilingual

set -e

WORK_DIR="$1"
SUBTITLE_TYPE="${2:-chinese}"  # chinese or bilingual

cd "$WORK_DIR"

# Find files - use find to handle filenames with spaces
VIDEO_FILE=$(find . -maxdepth 1 -name "*.original.mp4" -type f | head -1)
SRT_FILE=$(find . -maxdepth 1 -name "*.zh-CN.srt" -type f | head -1)

if [[ -z "$VIDEO_FILE" ]]; then
    echo "❌ 未找到原始视频"
    exit 1
fi

if [[ -z "$SRT_FILE" ]]; then
    echo "❌ 未找到中文字幕"
    exit 1
fi

BASE_NAME="${SRT_FILE%.zh-CN.srt}"

# Find voice-map for Chinese dubbing (prefer non-.en version)
VOICE_MAP=$(find . -maxdepth 1 -name "*.voice-map.json" -type f | grep -v '\.en\.voice-map\.json' | head -1)

if [[ -z "$VOICE_MAP" ]]; then
    # Fallback to any voice-map
    VOICE_MAP=$(find . -maxdepth 1 -name "*.voice-map.json" -type f | head -1)
fi

if [[ -z "$VOICE_MAP" ]]; then
    echo "❌ 未找到配音元数据"
    exit 1
fi

echo "  视频文件：$VIDEO_FILE"
echo "  配音元数据：$VOICE_MAP"

# Merge audio segments and sync with video
echo "  合并音频并合成视频..."
python3 << EOF
import json
import subprocess
import os

# Load metadata
with open("$VOICE_MAP", 'r') as f:
    metadata = json.load(f)

segments = metadata['segments']

# Create concat file for ffmpeg
concat_file = "concat_list.txt"
with open(concat_file, 'w') as f:
    for seg in segments:
        if seg['file'] and os.path.exists(seg['file']):
            f.write(f"file '{seg['file']}'\n")

# Merge audio segments
if os.path.exists(concat_file):
    print("    合并音频片段...")
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_file,
        '-c', 'copy',
        f"$BASE_NAME.zh-CN.merged.mp3"
    ], check=True, capture_output=True)
else:
    print("    警告：无有效音频片段")

# Merge video with dubbed audio
print("    合成最终视频...")
subprocess.run([
    'ffmpeg', '-y',
    '-i', "$VIDEO_FILE",
    '-i', f"$BASE_NAME.zh-CN.merged.mp3",
    '-c:v', 'copy',
    '-c:a', 'aac',
    '-map', '0:v:0',
    '-map', '1:a:0',
    '-shortest',
    f"$BASE_NAME.zh-CN.final.mp4"
], check=True, capture_output=True)

# Try to add subtitles if available (use HandBrake for hard-burning)
if os.path.exists("$SRT_FILE"):
    print("    使用 HandBrake 硬烧字幕...")

    # Check if this is bilingual mode
    subtitle_type = "$SUBTITLE_TYPE"

    # Create ASS subtitle file for better font control
    import re

    def time_to_ms(time_str):
        match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
        if match:
            h, m, s, ms = map(int, match.groups())
            return h * 3600000 + m * 60000 + s * 1000 + ms
        return 0

    def ms_to_ass_time(ms):
        h = ms // 3600000
        ms %= 3600000
        m = ms // 60000
        ms %= 60000
        s = ms // 1000
        ms %= 1000
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    # Read Chinese subtitle
    with open("$SRT_FILE", 'r', encoding='utf-8') as f:
        srt_content = f.read()

    # Parse SRT
    blocks = []
    current_block = {'time': '', 'text': []}
    for line in srt_content.strip().split('\n'):
        line = line.strip()
        if not line:
            if current_block['text']:
                blocks.append(current_block)
            current_block = {'time': '', 'text': []}
            continue
        if '-->' in line:
            current_block['time'] = line
        elif line.isdigit():
            continue
        else:
            current_block['text'].append(line)
    if current_block['text']:
        blocks.append(current_block)

    # Check for bilingual subtitle file
    bilingual_blocks = []
    if subtitle_type == "bilingual":
        # Try to find English subtitle file
        import glob
        en_files = glob.glob("*.en.only.srt")
        if not en_files:
            en_files = glob.glob("*.en.srt")
        if en_files:
            en_file = en_files[0]
            print(f"    读取英文字幕：{en_file}")
            with open(en_file, 'r', encoding='utf-8') as f:
                en_content = f.read()

            # Parse English SRT (handle YouTube format with duplicates)
            en_blocks = []
            current_en = {'time': '', 'text': []}
            prev_text = ""
            for line in en_content.strip().split('\n'):
                line = line.strip()
                if not line:
                    if current_en['text']:
                        # Remove duplicate prefix
                        full_text = ' '.join(current_en['text'])
                        if full_text.startswith(prev_text):
                            new_part = full_text[len(prev_text):].strip()
                            if new_part:
                                current_en['text'] = [new_part]
                            else:
                                current_en['text'] = [prev_text]
                        en_blocks.append(current_en)
                        prev_text = full_text
                    current_en = {'time': '', 'text': []}
                    continue
                if '-->' in line:
                    current_en['time'] = line
                elif line.isdigit():
                    continue
                elif line.startswith('Language:') or line.startswith('align:'):
                    continue
                else:
                    current_en['text'].append(line)
            if current_en['text']:
                en_blocks.append(current_en)

            # Match English with Chinese
            print(f"    匹配中英文字幕...")
            for i, (cn_block, en_block) in enumerate(zip(blocks, en_blocks)):
                cn_text = ' '.join(cn_block['text'])
                en_text = ' '.join(en_block['text']).strip()
                time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', cn_block['time'])
                if time_match:
                    start, end = time_match.groups()
                    bilingual_blocks.append({
                        'start': start,
                        'end': end,
                        'cn': cn_text,
                        'en': en_text
                    })

    # Write ASS subtitle file
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,STHeiti,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,2,1,2,10,10,60,1
Style: English,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,1,0,2,10,10,15,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open("subtitles.ass", 'w', encoding='utf-8') as f:
        f.write(ass_header)

        if subtitle_type == "bilingual" and bilingual_blocks:
            print(f"    生成双语 ASS 字幕：{len(bilingual_blocks)} 条")
            for block in bilingual_blocks:
                start = ms_to_ass_time(time_to_ms(block['start']))
                end = ms_to_ass_time(time_to_ms(block['end']))
                # Escape ASS special characters
                cn_text = block['cn'].replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
                en_text = block['en'].replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
                f.write(f"Dialogue: 0,{start},{end},Chinese,,0,0,0,,{{\\an8}}{cn_text}\\N{{\\fs32}}{en_text}\n")
        else:
            print(f"    生成中文 ASS 字幕：{len(blocks)} 条")
            for block in blocks:
                time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', block['time'])
                if time_match:
                    start, end = time_match.groups()
                    start = ms_to_ass_time(time_to_ms(start))
                    end = ms_to_ass_time(time_to_ms(end))
                    cn_text = ' '.join(block['text']).replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
                    f.write(f"Dialogue: 0,{start},{end},Chinese,,0,0,0,,{{\\an8}}{cn_text}\n")

    print("    ASS 字幕文件已创建：subtitles.ass")

    # Use HandBrakeCLI to burn subtitles
    try:
        subprocess.run([
            'HandBrakeCLI',
            '-i', f"$BASE_NAME.zh-CN.final.mp4",
            '-o', f"$BASE_NAME.zh-CN.hardsub.mp4",
            '--subtitle-burn=1',
            '--subtitle=1',
            '-e', 'x264',
            '-q', '20'
        ], check=True, capture_output=True, text=True)
        print("    HandBrake 硬烧字幕完成")

        # Replace final video with hardsubbed version
        os.rename(f"$BASE_NAME.zh-CN.hardsub.mp4", f"$BASE_NAME.zh-CN.final.mp4")
        print("    已替换为硬烧字幕版本")
    except subprocess.CalledProcessError as e:
        print(f"    HandBrake 失败：{e.stderr[:200] if e.stderr else e}")
    except FileNotFoundError:
        print("    未找到 HandBrakeCLI，跳过硬烧")
    except Exception as e:
        print(f"    硬烧失败：{e}")

# Cleanup temp files
if os.path.exists(concat_file):
    os.remove(concat_file)

print(f"  最终文件：$BASE_NAME.zh-CN.final.mp4")

# Get file info
result = subprocess.run([
    'ffprobe', '-v', 'error',
    '-select_streams', 'v:0',
    '-show_entries', 'stream=width,height,duration',
    '-of', 'csv=p=0',
    f"$BASE_NAME.zh-CN.final.mp4"
], capture_output=True, text=True)

info = result.stdout.strip().split(',')
if len(info) >= 3:
    width, height, duration = info[0], info[1], info[2]
    print(f"  分辨率：{width}x{height}")
    print(f"  时长：{float(duration):.1f}秒")

# Get file size
file_size = os.path.getsize(f"$BASE_NAME.zh-CN.final.mp4")
if file_size > 1024*1024:
    print(f"  大小：{file_size/(1024*1024):.1f}MB")
else:
    print(f"  大小：{file_size/1024:.1f}KB")
EOF

echo "✅ 视频合成完成"
