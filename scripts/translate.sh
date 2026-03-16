#!/bin/bash
# YouTube Video Translator - Main Entry Point
# Usage: ./translate.sh <YouTube_URL> [--cleanup] [--lang LANG] [--voice-library]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
CONFIG_FILE="$SCRIPT_DIR/../config/default.json"
ENV_FILE="$SCRIPT_DIR/../.env"

# Load environment variables from .env file if exists
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
    echo "✅ 已加载环境变量：$ENV_FILE"
elif [[ -f "$ENV_FILE.example" ]]; then
    echo "⚠️ 未找到 .env 文件"
    echo "💡 复制 .env.example 为 .env 并配置 API Key："
    echo "   cp $ENV_FILE.example $ENV_FILE"
    echo "   然后编辑 $ENV_FILE 填入你的 API Key"
    echo ""
fi

# Parse arguments
VIDEO_URL=""
CLEANUP=false
TARGET_LANG="zh-CN"
VOICE_LIBRARY=false
SUBTITLE_TYPE="chinese"  # default: chinese, option: bilingual
SUBTITLE_SOURCE="download"  # default: download, option: whisper

while [[ $# -gt 0 ]]; do
    case $1 in
        --cleanup)
            CLEANUP=true
            shift
            ;;
        --lang)
            TARGET_LANG="$2"
            shift 2
            ;;
        --voice-library)
            VOICE_LIBRARY=true
            shift
            ;;
        --subtitles)
            SUBTITLE_TYPE="$2"
            shift 2
            ;;
        --subtitle-source)
            SUBTITLE_SOURCE="$2"
            shift 2
            ;;
        *)
            if [[ -z "$VIDEO_URL" ]]; then
                VIDEO_URL="$1"
            fi
            shift
            ;;
    esac
done

if [[ -z "$VIDEO_URL" ]]; then
    echo "❌ 错误：请提供 YouTube 视频链接"
    echo "用法：./translate.sh <URL> [--cleanup] [--lang LANG] [--voice-library]"
    exit 1
fi

# Check environment
if [[ -z "$ELEVENLABS_API_KEY" ]]; then
    echo "❌ 错误：未设置 ELEVENLABS_API_KEY 环境变量"
    echo "请执行：export ELEVENLABS_API_KEY=\"your_key\""
    exit 1
fi

# Check dependencies
command -v yt-dlp >/dev/null 2>&1 || { echo "❌ 需要安装 yt-dlp: brew install yt-dlp"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "❌ 需要安装 ffmpeg: brew install ffmpeg"; exit 1; }

# Extract video ID/title for directory name
VIDEO_ID=$(yt-dlp --get-id "$VIDEO_URL" 2>/dev/null || echo "unknown")
SAFE_TITLE=$(yt-dlp --get-title "$VIDEO_URL" 2>/dev/null | sed 's/[^a-zA-Z0-9_-]/_/g' | cut -c1-50 || echo "video")
WORK_DIR="$BASE_DIR/videos/${VIDEO_ID}_${SAFE_TITLE}"

echo "🎬 YouTube 视频翻译工具"
echo "━━━━━━━━━━━━━━━━━━━━━━"
echo "📺 视频链接：$VIDEO_URL"
echo "📁 工作目录：$WORK_DIR"
echo "🌐 目标语言：$TARGET_LANG"
echo "🎙️ 声音克隆：$([ "$VOICE_LIBRARY" = true ] && echo "使用预设声音" || echo "克隆原声")"
echo "📝 字幕类型：$([ "$SUBTITLE_TYPE" = "bilingual" ] && echo "中英文双语" || echo "仅中文")"
echo "📡 字幕来源：$([ "$SUBTITLE_SOURCE" = "whisper" ] && echo "Whisper 本地转录" || echo "下载英文字幕")"
echo ""

# Create working directory
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Helper function to print step status
print_status() {
    local step=$1
    local total=$2
    local desc=$3
    local status=$4
    local icon=""
    case $status in
        "running") icon="🔄" ;;
        "done") icon="✅" ;;
        "fail") icon="❌" ;;
        "warn") icon="⚠️" ;;
    esac
    echo -ne "\r${icon} 步骤 ${step}/${total}: ${desc}   "
}

mark_step_done() {
    local step=$1
    local total=$2
    local desc=$3
    echo -e "\r✅ 步骤 ${step}/${total}: ${desc} [完成]"
}

mark_step_fail() {
    local step=$1
    local total=$2
    local desc=$3
    echo -e "\r❌ 步骤 ${step}/${total}: ${desc} [失败]"
}

# Step 1: Download video and subtitles
print_status 1 5 "下载视频和字幕" "running"
bash "$SCRIPT_DIR/download.sh" "$VIDEO_URL" "$TARGET_LANG" "$SUBTITLE_SOURCE"
if [[ $? -ne 0 ]]; then
    mark_step_fail 1 5 "下载视频和字幕"
    echo "⚠️ 下载失败，尝试继续..."
else
    mark_step_done 1 5 "下载视频和字幕"
fi

# Step 2: Extract/Translate subtitles
print_status 2 5 "处理字幕" "running"
bash "$SCRIPT_DIR/transcribe.sh" "$WORK_DIR" "$TARGET_LANG" "$SUBTITLE_TYPE" "$SUBTITLE_SOURCE"
if [[ $? -ne 0 ]]; then
    mark_step_fail 2 5 "处理字幕"
    echo "⚠️ 字幕处理失败，尝试继续..."
else
    mark_step_done 2 5 "处理字幕"
fi

# Step 3: Generate dubbed audio
print_status 3 5 "生成中文配音" "running"
# Pass empty string for VOICE_NAME when VOICE_LIBRARY is false (use default voice)
VOICE_PARAM=""
if [[ "$VOICE_LIBRARY" = true ]]; then
    VOICE_PARAM="library"
fi
bash "$SCRIPT_DIR/dub.sh" "$WORK_DIR" "$TARGET_LANG" "$VOICE_PARAM"
if [[ $? -ne 0 ]]; then
    mark_step_fail 3 5 "生成中文配音"
    echo "❌ 配音生成失败"
    exit 1
else
    mark_step_done 3 5 "生成中文配音"
fi

# Step 4: Merge video and audio
print_status 4 5 "合成视频" "running"
bash "$SCRIPT_DIR/merge.sh" "$WORK_DIR" "$SUBTITLE_TYPE"
if [[ $? -ne 0 ]]; then
    mark_step_fail 4 5 "合成视频"
    echo "❌ 视频合成失败"
    exit 1
else
    mark_step_done 4 5 "合成视频"
fi

# Step 5: Cleanup (optional)
if [[ "$CLEANUP" = true ]]; then
    mark_step_done 5 5 "清理中间文件"
    bash "$SCRIPT_DIR/cleanup.sh" "$WORK_DIR"
else
    echo ""
    echo "💾 中间文件已保留在工作区"
fi

echo ""
echo "✅ 翻译完成！"
