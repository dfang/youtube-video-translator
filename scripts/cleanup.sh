#!/bin/bash
# Cleanup intermediate files
# Usage: ./cleanup.sh <WORK_DIR>

set -e

WORK_DIR="$1"

cd "$WORK_DIR"

echo "  清理中间文件..."

# Keep only final output
FINAL_FILE=$(ls *.zh-CN.final.mp4 2>/dev/null | head -1)

if [[ -z "$FINAL_FILE" ]]; then
    echo "  警告：未找到最终输出文件"
    exit 0
fi

BASE_NAME="${FINAL_FILE%.zh-CN.final.mp4}"

# Files to keep
KEEP_FILES=(
    "$FINAL_FILE"
)

# Remove intermediate files
PATTERNS=(
    "*.original.mp4"
    "*.audio.mp3"
    "*.vtt"
    "*.en.srt"
    "*.en.vtt"
    "*.zh-CN.srt"
    "*.voice-map.json"
    "*.seg.*.mp3"
    "*.zh-CN.merged.mp3"
    "*.zh-CN.mp3"
    "concat_list.txt"
)

for pattern in "${PATTERNS[@]}"; do
    for file in $pattern; do
        if [[ -f "$file" ]]; then
            echo "    删除：$file"
            rm -f "$file"
        fi
    done
done

echo "  保留：$FINAL_FILE"
echo "✅ 清理完成"
