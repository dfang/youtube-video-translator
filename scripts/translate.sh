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
TTS_ENGINE="edge-tts"  # default: edge-tts, option: piper-tts
SUBTITLE_TYPE="chinese"  # default: chinese, option: bilingual
SUBTITLE_SOURCE="download"  # default: download, option: whisper
AUDIO_MODE="dub"  # default: dub (only dubbed audio), option: original (only original audio)
WHISPER_MODEL="large-v3-turbo"  # default: large-v3-turbo, options: tiny/base/small/medium/large-v3/large-v3-turbo
VOCAB_FILE="medical"  # default: medical built-in vocabulary

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
        --tts-engine)
            TTS_ENGINE="$2"
            shift 2
            ;;
        --audio-mode)
            AUDIO_MODE="$2"
            shift 2
            ;;
        --whisper-model)
            WHISPER_MODEL="$2"
            shift 2
            ;;
        --vocab)
            VOCAB_FILE="$2"
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
echo "📡 字幕来源：$( [ "$SUBTITLE_SOURCE" = "whisper" ] && echo "Whisper 本地转录" || ( [ "$SUBTITLE_SOURCE" = "whisperx" ] && echo "faster-whisper + whisperx 对齐" || echo "下载英文字幕" ))"
echo "🔊 TTS 引擎：$TTS_ENGINE"
echo "🎵 音频模式：$([ "$AUDIO_MODE" = "original" ] && echo "仅原音" || echo "仅配音")"
if [[ "$SUBTITLE_SOURCE" == "whisper" || "$SUBTITLE_SOURCE" == "whisperx" ]]; then
    echo "🧠 Whisper 模型：$WHISPER_MODEL"
    if [[ -n "$VOCAB_FILE" ]]; then
        echo "📖 词汇表：$VOCAB_FILE"
    fi
fi
echo ""

# Create working directory
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Enable Telegram-style progress output by default.
# Set TELEGRAM_PROGRESS=0 to disable explicitly.
TELEGRAM_PROGRESS="${TELEGRAM_PROGRESS:-1}"

# Progress output mode:
# - interactive TTY: keep single-line refresh
# - non-interactive/Telegram: print newline events for each step update
PROGRESS_EVENT_MODE=false
if [[ "$TELEGRAM_PROGRESS" != "0" || ! -t 1 || -n "$TELEGRAM_CHAT_ID" ]]; then
    PROGRESS_EVENT_MODE=true
fi

emit_progress_event() {
    local step=$1
    local total=$2
    local status=$3
    local desc=$4
    # Machine-readable event for Telegram/automation parsers.
    # Format: TG_PROGRESS|<step>|<total>|<status>|<description>
    echo "TG_PROGRESS|${step}|${total}|${status}|${desc}"
}

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
    if [[ "$PROGRESS_EVENT_MODE" == "true" ]]; then
        echo "${icon} 步骤 ${step}/${total}: ${desc}"
        emit_progress_event "$step" "$total" "$status" "$desc"
    else
        echo -ne "\r${icon} 步骤 ${step}/${total}: ${desc}   "
    fi
}

mark_step_done() {
    local step=$1
    local total=$2
    local desc=$3
    if [[ "$PROGRESS_EVENT_MODE" == "true" ]]; then
        echo "✅ 步骤 ${step}/${total}: ${desc} [完成]"
        emit_progress_event "$step" "$total" "done" "$desc"
    else
        echo -e "\r✅ 步骤 ${step}/${total}: ${desc} [完成]"
    fi
}

mark_step_fail() {
    local step=$1
    local total=$2
    local desc=$3
    if [[ "$PROGRESS_EVENT_MODE" == "true" ]]; then
        echo "❌ 步骤 ${step}/${total}: ${desc} [失败]"
        emit_progress_event "$step" "$total" "fail" "$desc"
    else
        echo -e "\r❌ 步骤 ${step}/${total}: ${desc} [失败]"
    fi
}

cleanup_temp_translate_scripts() {
    local count
    count=$(find "$WORK_DIR" -maxdepth 1 -type f \( -name "trans.py" -o -name "trans_full.py" -o -name "trans_*.py" \) | wc -l | tr -d ' ')
    if [[ "${count:-0}" -gt 0 ]]; then
        find "$WORK_DIR" -maxdepth 1 -type f \( -name "trans.py" -o -name "trans_full.py" -o -name "trans_*.py" \) -delete
        echo "🧹 已清理临时翻译脚本：$count 个"
    fi
}

# Step 1: Download video and subtitles
print_status 1 5 "下载视频和字幕" "running"
bash "$SCRIPT_DIR/download.sh" "$VIDEO_URL" "$TARGET_LANG" "$SUBTITLE_SOURCE" "$WORK_DIR"
if [[ $? -ne 0 ]]; then
    mark_step_fail 1 5 "下载视频和字幕"
    echo "⚠️ 下载失败，尝试继续..."
else
    mark_step_done 1 5 "下载视频和字幕"
fi

# Step 2: Extract/Translate subtitles
print_status 2 5 "处理字幕" "running"
# Set AUTO_CONFIRM to skip interactive prompts in transcribe.sh
export AUTO_CONFIRM=true
bash "$SCRIPT_DIR/transcribe.sh" "$WORK_DIR" "$TARGET_LANG" "$SUBTITLE_TYPE" "$SUBTITLE_SOURCE" "$WHISPER_MODEL" "$VOCAB_FILE"
if [[ $? -ne 0 ]]; then
    mark_step_fail 2 5 "处理字幕"
    echo "⚠️ 字幕处理失败，尝试继续..."
else
    mark_step_done 2 5 "处理字幕"
fi
cleanup_temp_translate_scripts

# Step 3: Generate dubbed audio (skip if original audio mode)
if [[ "$AUDIO_MODE" != "original" ]]; then
    print_status 3 5 "生成中文配音" "running"
    # Pass empty string for VOICE_NAME when VOICE_LIBRARY is false (use default voice)
    VOICE_PARAM=""
    if [[ "$VOICE_LIBRARY" = true ]]; then
        VOICE_PARAM="library"
    fi
    bash "$SCRIPT_DIR/dub.sh" "$WORK_DIR" "$TARGET_LANG" "$VOICE_PARAM" "$TTS_ENGINE"
    if [[ $? -ne 0 ]]; then
        mark_step_fail 3 5 "生成中文配音"
        echo "❌ 配音生成失败"
        exit 1
    else
        mark_step_done 3 5 "生成中文配音"
    fi
else
    echo "⏭️ 跳过配音生成（仅原音模式）"
fi

# Step 4: Merge video and audio
print_status 4 5 "合成视频" "running"
bash "$SCRIPT_DIR/merge.sh" "$WORK_DIR" "$SUBTITLE_TYPE" "$AUDIO_MODE"
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
