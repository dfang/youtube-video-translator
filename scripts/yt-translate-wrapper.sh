#!/bin/bash
# Wrapper script for YouTube Video Translator
# This script is called by Claude Code and handles interactive prompting

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If any argument contains "--", we have explicit parameters
HAS_PARAMS=false
for arg in "$@"; do
    if [[ "$arg" == --* ]]; then
        HAS_PARAMS=true
        break
    fi
done

# If user provided explicit parameters, pass through directly
if [ "$HAS_PARAMS" = true ]; then
    exec bash "$SCRIPT_DIR/translate.sh" "$@"
fi

# If first argument is not a URL, show help
URL="$1"
if [[ -z "$URL" ]]; then
    echo "❌ 错误：请提供 YouTube 视频链接"
    echo "用法：./yt-translate-wrapper.sh <URL> [选项]"
    echo ""
    echo "可用选项："
    echo "  --audio-mode original|dub     音频模式（原音/配音）"
    echo "  --subtitle-source download|whisperx  字幕来源"
    echo "  --tts-engine edge-tts|piper-tts  TTS 引擎"
    echo "  --subtitles chinese|bilingual  字幕类型"
    echo "  --cleanup                      清理中间文件"
    exit 1
fi

# No parameters provided - output a prompt for Claude Code to handle
echo "🎬 YouTube 视频翻译工具"
echo "━━━━━━━━━━━━━━━━━━━━━━"
echo "📺 视频链接：$URL"
echo ""
echo "⚙️  未指定选项，使用默认配置："
echo "   - 字幕来源：download（下载 YouTube 英文字幕）"
echo "   - 音频模式：dub（生成中文配音）"
echo "   - TTS 引擎：edge-tts（在线免费）"
echo "   - 字幕类型：chinese（仅中文字幕）"
echo ""
echo "💡 如需自定义选项，请添加参数重新运行："
echo "   --audio-mode original|dub"
echo "   --subtitle-source download|whisperx"
echo "   --tts-engine edge-tts|piper-tts"
echo "   --subtitles chinese|bilingual"
echo ""
echo "开始执行..."
echo ""

# Run with defaults
exec bash "$SCRIPT_DIR/translate.sh" "$URL"
